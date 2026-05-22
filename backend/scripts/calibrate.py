"""Calibrate aggregator weights on the ground-truth dataset.

Pipeline:
  1. Load human + ai parquets, dedupe by text_hash.
  2. Run each sample through the live detector (POST /v1/detections) to get
     (statistical, patterns, llm_judge) sub-scores.
  3. Compare default ENV weights vs a logistic-regression fit
     (5-fold cross-validated) on the same features.
  4. Write models/aggregator_v1.json with the learned coefficients + metrics.

Usage:
    uv run python scripts/calibrate.py
    uv run python scripts/calibrate.py --api http://localhost:8010 --concurrency 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold

DEFAULT_W = {"statistical": 0.25, "patterns": 0.35, "llm_judge": 0.40}


def _load_dataset(human_paths: list[Path], ai_paths: list[Path]) -> pl.DataFrame:
    parts: list[pl.DataFrame] = []
    for p in human_paths:
        if p.exists():
            parts.append(pl.read_parquet(p).with_columns(pl.lit("human").alias("label")))
    for p in ai_paths:
        if p.exists():
            parts.append(pl.read_parquet(p).with_columns(pl.lit("ai").alias("label")))
    if not parts:
        raise SystemExit("no datasets found; run build_ground_truth.py and synth_ai_posts.py first")
    df = pl.concat(parts, how="diagonal_relaxed")
    df = df.unique(subset=["text_hash"], keep="first", maintain_order=True)
    return df


async def _detect_one(
    client: httpx.AsyncClient, api: str, token: str, text: str, mode: str
) -> dict[str, float] | None:
    body = {
        "text": text,
        "mode": mode,
        "options": {"include_signals": True, "include_evidence": False, "include_rubric_scores": False},
    }
    try:
        resp = await client.post(
            f"{api}/v1/detections",
            json=body,
            headers={"X-API-Key": token, "Content-Type": "application/json"},
            timeout=45.0,
        )
        resp.raise_for_status()
        r = resp.json()
        sig = r.get("signals") or {}
        stat = (sig.get("statistical") or {}).get("score")
        pat = (sig.get("patterns") or {}).get("score")
        llm = (sig.get("llm_judge") or {}).get("score")
        if stat is None or pat is None or llm is None:
            return None
        return {
            "statistical": float(stat),
            "patterns": float(pat),
            "llm_judge": float(llm),
            "default_ai_prob": float(r["result"]["ai_probability"]),
        }
    except Exception as exc:
        print(f"  ! detect failed: {type(exc).__name__}: {str(exc)[:100]}", file=sys.stderr)
        return None


async def _run_detections(
    df: pl.DataFrame, api: str, token: str, concurrency: int, mode: str
) -> pl.DataFrame:
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict[str, Any]] = []
    lock = asyncio.Lock()

    async def worker(client: httpx.AsyncClient, idx: int, item: dict[str, Any]) -> None:
        async with sem:
            features = await _detect_one(client, api, token, item["text"], mode)
        if features is None:
            return
        async with lock:
            rows.append(
                {
                    "text_hash": item["text_hash"],
                    "label": item["label"],
                    "language": item.get("language"),
                    "source": item.get("source"),
                    **features,
                }
            )
            if len(rows) % 25 == 0:
                print(f"  {len(rows)}/{len(df)} samples scored")

    items = df.to_dicts()
    async with httpx.AsyncClient(timeout=60.0) as client:
        await asyncio.gather(*(worker(client, i, item) for i, item in enumerate(items)))
    return pl.DataFrame(rows)


def _ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error."""
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi if i < n_bins - 1 else y_prob <= hi)
        if mask.sum() == 0:
            continue
        bin_acc = float(y_true[mask].mean())
        bin_conf = float(y_prob[mask].mean())
        ece += abs(bin_acc - bin_conf) * mask.sum() / n
    return float(ece)


def _metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    y_pred = (y_prob >= threshold).astype(int)
    return {
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "auroc": float(roc_auc_score(y_true, y_prob)) if len(set(y_true)) > 1 else float("nan"),
        "ece": _ece(y_true, y_prob),
    }


def _print_metrics(label: str, m: dict[str, float]) -> None:
    print(
        f"  {label:30s} F1={m['f1']:.3f}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
        f"AUROC={m['auroc']:.3f}  ECE={m['ece']:.3f}"
    )


async def main_async(args: argparse.Namespace) -> int:
    human_paths = [Path(p.strip()) for p in args.human.split(",") if p.strip()]
    ai_paths = [Path(p.strip()) for p in args.ai.split(",") if p.strip()]
    print("Loading datasets:")
    print(f"  human: {[str(p) for p in human_paths]}")
    print(f"  ai:    {[str(p) for p in ai_paths]}")
    df = _load_dataset(human_paths, ai_paths)
    print(f"Total samples: {len(df)}  (human={int((df['label']=='human').sum())}  ai={int((df['label']=='ai').sum())})")

    print(
        f"\nScoring through detector at {args.api} (mode={args.mode}, "
        f"concurrency={args.concurrency})..."
    )
    feats = await _run_detections(df, args.api, args.token, args.concurrency, args.mode)
    if feats.is_empty():
        print("ERROR: no detections produced", file=sys.stderr)
        return 1

    feats = feats.with_columns(pl.when(pl.col("label") == "ai").then(1).otherwise(0).alias("y"))
    print(f"\nUsable samples: {len(feats)}  (human={int((feats['y']==0).sum())}  ai={int((feats['y']==1).sum())})")

    feature_cols = ["statistical", "patterns", "llm_judge"]
    X = feats.select(feature_cols).to_numpy()
    y = feats["y"].to_numpy()
    default_prob = feats["default_ai_prob"].to_numpy()
    if "weight" in feats.columns:
        sample_weight = feats["weight"].cast(pl.Float64).fill_null(1.0).to_numpy()
        boosted = int(((sample_weight - 1.0).abs() > 1e-6).sum())
        if boosted:
            print(f"  Using sample_weight (mean={sample_weight.mean():.2f}, "
                  f"max={sample_weight.max():.1f}, boosted={boosted})")
    else:
        import numpy as _np

        sample_weight = _np.ones(len(feats), dtype=float)

    print("\n=== Default ENV weights (statistical=0.25, patterns=0.35, llm=0.40) ===")
    default_metrics = _metrics(y, default_prob)
    _print_metrics("default", default_metrics)

    # C=0.3 — stronger L2 regularization keeps coefficients modest, so a
    # mid-range layer score (e.g. LLM 0.16) cannot single-handedly push final
    # probability into the 'likely_human' zone for an obvious human text.
    LR_KWARGS = {"C": 0.3, "class_weight": "balanced", "max_iter": 1000}

    print(f"\n=== Logistic regression (5-fold CV, C={LR_KWARGS['C']}) ===")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_probs = np.zeros_like(y, dtype=float)
    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y)):
        m = LogisticRegression(**LR_KWARGS)
        m.fit(X[train_idx], y[train_idx], sample_weight=sample_weight[train_idx])
        cv_probs[test_idx] = m.predict_proba(X[test_idx])[:, 1]
    cv_metrics = _metrics(y, cv_probs)
    _print_metrics("logistic (5-fold CV)", cv_metrics)

    final = LogisticRegression(**LR_KWARGS)
    final.fit(X, y, sample_weight=sample_weight)
    coefs = final.coef_[0].tolist()
    intercept = float(final.intercept_[0])
    final_metrics = _metrics(y, final.predict_proba(X)[:, 1])
    _print_metrics("logistic (full-fit, train)", final_metrics)

    print(f"\nLearned coefficients: stat={coefs[0]:+.3f}  pat={coefs[1]:+.3f}  llm={coefs[2]:+.3f}  bias={intercept:+.3f}")

    # Isotonic calibration on out-of-fold CV probabilities. This maps the raw
    # logistic output to true empirical frequency, so a logit-distorted 22%
    # becomes the actual ~5-8% that the data supports.
    print("\n=== Isotonic calibration (on CV out-of-fold probs) ===")
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(cv_probs, y, sample_weight=sample_weight)
    calibrated_probs = iso.predict(cv_probs)
    calibrated_metrics = _metrics(y, calibrated_probs)
    _print_metrics("isotonic-on-CV", calibrated_metrics)

    # Serialise the isotonic curve as a piecewise-linear (x, y) lookup.
    iso_x = iso.X_thresholds_.tolist()
    iso_y = iso.y_thresholds_.tolist()
    print(f"  curve knots: {len(iso_x)}")

    print("\n=== Per-language slice (CV probs, post-isotonic) ===")
    for lang in ["en", "ru"]:
        mask = feats["language"].to_numpy() == lang
        if mask.sum() < 5:
            continue
        slice_metrics = _metrics(y[mask], calibrated_probs[mask])
        _print_metrics(f"{lang} (n={int(mask.sum())})", slice_metrics)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "v1",
        "fitted_on": {
            "human": [str(p) for p in human_paths],
            "ai": [str(p) for p in ai_paths],
            "mode": args.mode,
            "samples_total": int(len(feats)),
            "samples_human": int((feats["y"] == 0).sum()),
            "samples_ai": int((feats["y"] == 1).sum()),
        },
        "features": feature_cols,
        "coefficients": dict(zip(feature_cols, coefs)),
        "intercept": intercept,
        "use_logistic": True,
        "isotonic": {"x": iso_x, "y": iso_y},
        "metrics": {
            "default": default_metrics,
            "logistic_cv": cv_metrics,
            "logistic_full_train": final_metrics,
            "isotonic_cv": calibrated_metrics,
        },
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWrote {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human", default="data/ground_truth/v1.parquet")
    parser.add_argument("--ai", default="data/ground_truth/synthetic_ai_v1.parquet")
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    parser.add_argument("--token", default=os.environ.get("AIDETECT_INTERNAL_TOKEN", "dev-token-change-me"))
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--mode",
        default="fast",
        choices=["fast", "balanced", "thorough"],
        help="Detection mode used during calibration. balanced enables sentence-level judge.",
    )
    parser.add_argument("--output", default="models/aggregator_v1.json")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
