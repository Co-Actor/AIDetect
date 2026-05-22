"""Combine layer scores into a final probability + verdict + severity.

If ``models/aggregator_v1.json`` exists (produced by ``scripts/calibrate.py``),
the aggregator uses the fitted logistic-regression coefficients via a sigmoid.
Otherwise it falls back to the linear weighted average from ENV.
"""
from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from aidetect.config import Settings
from aidetect.schemas.detection import (
    DetectionResultBlock,
    LLMJudgeSignal,
    PatternsSignal,
    Severity,
    StatisticalSignal,
    Verdict,
)

logger = logging.getLogger(__name__)

_CALIBRATION_PATH = Path(__file__).resolve().parents[3] / "models" / "aggregator_v1.json"


@lru_cache(maxsize=1)
def _load_calibration() -> dict[str, Any] | None:
    if not _CALIBRATION_PATH.exists():
        return None
    try:
        data = json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[aggregator] cannot read %s: %s", _CALIBRATION_PATH, exc)
        return None
    if not data.get("use_logistic"):
        return None
    if "coefficients" not in data or "intercept" not in data:
        return None
    iso = data.get("isotonic")
    has_iso = (
        isinstance(iso, dict)
        and isinstance(iso.get("x"), list)
        and isinstance(iso.get("y"), list)
        and len(iso["x"]) >= 2
        and len(iso["x"]) == len(iso["y"])
    )
    logger.info(
        "[aggregator] using calibrated weights from %s (isotonic=%s)",
        _CALIBRATION_PATH, has_iso,
    )
    return data


def _apply_isotonic(p: float, curve: dict[str, list[float]]) -> float:
    """Piecewise-linear interpolation on the isotonic curve from calibrate.py."""
    xs = curve["x"]
    ys = curve["y"]
    if p <= xs[0]:
        return max(0.0, min(1.0, ys[0]))
    if p >= xs[-1]:
        return max(0.0, min(1.0, ys[-1]))
    # Binary search for the right interval.
    lo, hi = 0, len(xs) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if xs[mid] <= p:
            lo = mid
        else:
            hi = mid
    x0, x1 = xs[lo], xs[hi]
    y0, y1 = ys[lo], ys[hi]
    if x1 == x0:
        return max(0.0, min(1.0, y0))
    t = (p - x0) / (x1 - x0)
    return max(0.0, min(1.0, y0 + t * (y1 - y0)))


def reset_calibration_cache() -> None:
    _load_calibration.cache_clear()


def _verdict_for(p: float) -> Verdict:
    # Thresholds align with ZeroGPT-style binary cutoff at 0.5 but give a wider
    # human band: anything < 0.30 is treated as human, < 0.50 as likely_human.
    if p < 0.30:
        return "human"
    if p < 0.50:
        return "likely_human"
    if p < 0.65:
        return "uncertain"
    if p < 0.80:
        return "likely_ai"
    return "ai"


def _severity_for(p: float) -> Severity:
    if p < 0.50:
        return "low"
    if p < 0.75:
        return "medium"
    return "high"


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _logistic_probability(scores: dict[str, float], cal: dict[str, Any]) -> float | None:
    feature_order: list[str] = cal.get("features") or list(cal["coefficients"].keys())
    if any(scores.get(f) is None for f in feature_order):
        return None
    z = float(cal["intercept"])
    coefs = cal["coefficients"]
    for f in feature_order:
        z += float(coefs[f]) * float(scores[f])
    return _sigmoid(z)


def _linear_probability(
    scores: dict[str, float | None], settings: Settings
) -> tuple[float, float]:
    weights = {
        "statistical": settings.agg_weight_statistical,
        "patterns": settings.agg_weight_patterns,
        "llm_judge": settings.agg_weight_llm_judge,
    }
    available = {k: v for k, v in scores.items() if v is not None}
    if not available:
        return 0.5, 0.0
    total_w = sum(weights[k] for k in available)
    weighted = sum(scores[k] * weights[k] for k in available)  # type: ignore[operator]
    return max(0.0, min(1.0, weighted / total_w)), total_w


def aggregate(
    statistical: StatisticalSignal | None,
    patterns: PatternsSignal | None,
    llm_judge: LLMJudgeSignal | None,
    settings: Settings,
) -> DetectionResultBlock:
    scores: dict[str, float | None] = {
        "statistical": statistical.score if statistical else None,
        "patterns": patterns.score if patterns else None,
        "llm_judge": llm_judge.score if llm_judge else None,
    }

    cal = _load_calibration()
    ai_prob: float | None = None
    if cal is not None:
        non_null = {k: v for k, v in scores.items() if v is not None}
        ai_prob = _logistic_probability(non_null, cal)
        if ai_prob is not None and isinstance(cal.get("isotonic"), dict):
            ai_prob = _apply_isotonic(ai_prob, cal["isotonic"])

    if ai_prob is None:
        ai_prob, _ = _linear_probability(scores, settings)

    # Sanity floor: when no individual layer signals more than 30% AI AND
    # patterns layer is quiet, the calibrated aggregator can still output ~20%
    # due to a residual logit prior (LLM-judge over-flags some formalised but
    # human prose). In that unanimous-human case, trust the layers and clamp
    # the final probability. We do NOT apply the floor when patterns >= 0.15:
    # concrete AI phrase/structure hits are our most reliable signal, so any
    # meaningful patterns score means we keep the calibrated number.
    pat_score = scores.get("patterns") or 0.0
    non_null_scores = [v for v in scores.values() if v is not None]
    if non_null_scores and pat_score < 0.15:
        max_layer = max(non_null_scores)
        if max_layer < 0.30:
            # Linear cap: max_layer=0 → 0.03, max_layer=0.30 → 0.12.
            cap = 0.03 + (0.12 - 0.03) * (max_layer / 0.30)
            ai_prob = min(ai_prob, cap)
        elif max_layer < 0.40:
            # Soft cap in the borderline zone: ≤ 0.20.
            ai_prob = min(ai_prob, 0.20)

    ai_prob = max(0.0, min(1.0, ai_prob))
    confidence = 2.0 * abs(ai_prob - 0.5)

    return DetectionResultBlock(
        ai_probability=round(ai_prob, 4),
        human_probability=round(1.0 - ai_prob, 4),
        verdict=_verdict_for(ai_prob),
        confidence=round(confidence, 4),
        severity=_severity_for(ai_prob),
    )
