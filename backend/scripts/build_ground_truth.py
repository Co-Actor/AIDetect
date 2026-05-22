"""Build human-labelled ground truth from the Co.Actor read-only DB.

Picks `post_versions` whose stored M9 (ZeroGPT) score >= 0.8 — i.e. ZeroGPT
labelled them as human-like — and exports them as parquet for calibration.

Usage:
    uv run python scripts/build_ground_truth.py --dry-run
    uv run python scripts/build_ground_truth.py --output data/ground_truth/v1.parquet
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

import asyncpg
import polars as pl

from aidetect.config import get_settings


SQL_HUMAN = """
SELECT
    pv.id::text                                        AS id,
    pv.body                                            AS text,
    (pv.meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float
                                                       AS m9_human_score,
    coalesce(pv.meta->>'platform', 'unknown')          AS platform,
    pv.created_at                                      AS created_at
FROM post_versions pv
WHERE pv.meta ? 'quality_scores'
  AND (pv.meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float >= 0.80
  AND length(pv.body) >= 80
ORDER BY pv.created_at DESC
LIMIT 400
"""

SQL_STATS = """
SELECT
    count(*) FILTER (WHERE meta ? 'quality_scores')                                 AS with_quality,
    count(*) FILTER (
        WHERE (meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float >= 0.8
    )                                                                                AS weak_human,
    count(*) FILTER (
        WHERE (meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float < 0.5
    )                                                                                AS weak_ai,
    count(*)                                                                         AS total
FROM post_versions
"""


def detect_lang(text: str) -> str:
    """Cheap latin-vs-cyrillic split — good enough for our two languages."""
    if re.search(r"[А-Яа-яЁё]", text):
        return "ru"
    return "en"


async def fetch_rows(dsn: str) -> tuple[dict, list[asyncpg.Record]]:
    conn = await asyncpg.connect(dsn)
    try:
        stats = await conn.fetchrow(SQL_STATS)
        rows = await conn.fetch(SQL_HUMAN)
        return dict(stats) if stats else {}, rows
    finally:
        await conn.close()


def deduplicate(rows: list[asyncpg.Record]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        text = (r["text"] or "").strip()
        if len(text) < 80:
            continue
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(
            {
                "id": str(r["id"]),
                "text": text,
                "text_hash": h,
                "label": "human",
                "weight": float(r["m9_human_score"] or 0.8),
                "language": detect_lang(text),
                "platform": (r["platform"] or "unknown").lower(),
                "source": "coactor:m9>=0.8",
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "length_chars": len(text),
            }
        )
    return out


def write_parquet(samples: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(samples)
    df.write_parquet(output)


def print_breakdown(samples: list[dict]) -> None:
    if not samples:
        print("(no samples)")
        return
    by_lang: dict[str, int] = {}
    by_platform: dict[str, int] = {}
    for s in samples:
        by_lang[s["language"]] = by_lang.get(s["language"], 0) + 1
        by_platform[s["platform"]] = by_platform.get(s["platform"], 0) + 1
    lengths = sorted(s["length_chars"] for s in samples)
    p50 = lengths[len(lengths) // 2]
    print(f"  total samples:    {len(samples)}")
    print(f"  by language:      {dict(sorted(by_lang.items()))}")
    print(f"  by platform:      {dict(sorted(by_platform.items()))}")
    print(f"  length p50:       {p50} chars")


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.coactor_database_url:
        print("ERROR: COACTOR_DATABASE_URL not set in backend/.env", file=sys.stderr)
        return 1

    dsn = settings.coactor_database_url.replace("postgresql+asyncpg://", "postgresql://")
    stats, rows = await fetch_rows(dsn)
    print("Co.Actor inventory:")
    print(f"  total post_versions:           {stats.get('total')}")
    print(f"  with quality_scores:           {stats.get('with_quality')}")
    print(f"  weak human  (M9 >= 0.8):       {stats.get('weak_human')}")
    print(f"  weak ai     (M9 <  0.5):       {stats.get('weak_ai')}")
    print()

    samples = deduplicate(rows)
    print("Selected (deduped, length >= 80 chars):")
    print_breakdown(samples)

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    output = Path(args.output)
    write_parquet(samples, output)
    print(f"\nWrote {len(samples)} samples to {output}")

    sidecar = output.with_suffix(output.suffix + ".meta.json")
    sidecar.write_text(
        json.dumps(
            {"source": "coactor:m9>=0.8", "samples": len(samples), "stats": dict(stats)},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default="data/ground_truth/v1.parquet")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
