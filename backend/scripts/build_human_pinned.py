"""Build a small high-confidence human anchor set the calibrator can lean on.

Includes:
  - the two user-provided RU texts that were mis-rated as `likely_human`
  - up to N short Russian posts from Co.Actor with M9 >= 0.85

Each row is written with weight=5.0 so a single anchor counts ~5x in fitting.

Usage:
    uv run python scripts/build_human_pinned.py --output data/ground_truth/human_pinned.parquet
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from pathlib import Path

import asyncpg
import polars as pl

from aidetect.config import get_settings


USER_TEXTS = [
    """Я уже некоторое время использую /remote-control и честно это удобно.

Запустить Claude Code из терминала на сервере и управлять с телефона, ноута, где бы я не находился.

Потом добавили Dispatch для Claude Cowork, с мобильного можно вызвать рабочую сессию на твоем пк.

А вчера еще и Channels, чтобы использовать Claude в тг боте.

Всё для того, чтобы мы как можно чаще крутили эти слоты токены 🎰""",
    """Не хватало конечно такой фичи: Claude Code умеет пользоваться не файлами, а самим пк.

Открывать приложения, печатать, делать скриншоты. Всё через CLI, без переключения на десктоп.

То есть клод написал код, скомпилировал, запустил приложение, прокликал, нашёл баг, починил, проверил фикс.

Пока только на Мак, и нужен Pro или Max подписка ✋

Включается через /mcp > computer-use.

Надеюсь, что в скором времени линукс и винду добавят.""",
    """Reading about all that beef in the fashion media made me think that soft-power industries like fashion, art, and surprisingly comms have a lot more in common than we may want to admit.


I'm a huge culture and fashion geek. Those who know me well remember the times I sew my own dresses that mimicked (only slighly) the fahion trends and designs of the fashion gods like ....  I haven't missed a Venice biennale for god know how long and the fact that any city I visit I start with a museum (at least I try) if that fails I opt for a local food market (because food is art as well). But I digress.

I'm sure a lot of us, comms pros have had this momet in our professional lifes when someone from financial or legal expresses a very firm opinion about the procedures that should be implemeted in comms, or (which even tops this) a construction team gives you "a few suggestions" on how to maximize your efforts.... the list is endless.
And it's not that we don't want imput from other team members. Trust me! It's more than needed! Especially at times when you need to know the terms, the stakeholders within the niche, when you want to understand the market, etc. But it's definitely NOT needed when you are doing the job the way it's supposed to be done.

The problem is very simple.
In order to be the CFO you have to know hard concrete things, in legal - the same, in construction - the same. I can't possibly know how to build a supermarket after doing a renovation in my one-bedroom.

But with social media being so penetrative - everyone has an instagram or facebook account now, everyone makes the assumption they KNOW BETTER. Because it seems that comms is not that hard.

The same with fashion. What's so hard about it? We wear clothing every day. Right? No.
The complex art of costume history, of art history...
I am a firm beliver that practice makes perfect with a right amount of talent.

So yes, we all can know at least smth but we can't blatantly assume that we can know better than people who have spent their lives doing this thing.""",
    """What is your competitive advantage in the current AI era market?
I was discussing this with my friends over the weekend.

Before AI, you had to have an idea. You had to act fast on it, and you had to have the skill and capacity to make that idea real. Right now, you can make it real with the help of an AI, and you can be very fast at doing it.

Say you have a project idea, and then another person has the same project idea, and then another one. It takes you literally no time to create those ideas in life, and then the market is over-saturated with the same businesses, and we can already see it right now. Why should a person buy your product?

Well, some of my friends said that it's the speed or your ability to code with an AI.
My idea is that the only thing that's going to make your product stand out is you and the power of your personal brand. That's the only thing that's going to separate and be a competitive advantage.

That, and of course, the quality of an idea. If your idea is a genius one and you're a unicorn, then you're going to stand out for itself, the way Clawd did.

But other than that, it's personal branding and personal relationships. I think companies should be paying more attention to it as well, because that also means that big corporations are going to have to be investing in their brands and in the personal brands of their employees more and more in the nearest future.""",
]


SQL_SHORT_RU = """
SELECT
    pv.id::text                                        AS id,
    pv.body                                            AS text,
    (pv.meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float
                                                       AS m9_human_score
FROM post_versions pv
WHERE pv.meta ? 'quality_scores'
  AND (pv.meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float >= 0.85
  AND length(pv.body) BETWEEN 200 AND 1200
  AND pv.body ~ '[ёЁа-яА-Я]'
ORDER BY pv.created_at DESC
LIMIT $1
"""

SQL_LONG_EN = """
SELECT
    pv.id::text                                        AS id,
    pv.body                                            AS text,
    (pv.meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float
                                                       AS m9_human_score
FROM post_versions pv
WHERE pv.meta ? 'quality_scores'
  AND (pv.meta->'quality_scores'->'metrics'->'M9'->>'normalized')::float >= 0.85
  AND length(pv.body) BETWEEN 1200 AND 4000
  AND pv.body !~ '[ёЁа-яА-Я]'
ORDER BY pv.created_at DESC
LIMIT $1
"""


def _detect_lang(text: str) -> str:
    return "ru" if re.search(r"[А-Яа-яЁё]", text) else "en"


def _row(text: str, source: str, m9: float | None, weight: float) -> dict:
    text = text.strip()
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "id": h[:16],
        "text": text,
        "text_hash": h,
        "label": "human",
        "weight": weight,
        "language": _detect_lang(text),
        "platform": "unknown",
        "source": source,
        "created_at": None,
        "length_chars": len(text),
    }


async def fetch_short_ru(dsn: str, limit: int) -> list[dict]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(SQL_SHORT_RU, limit)
    finally:
        await conn.close()
    return [
        _row(r["text"] or "", source="coactor:short_ru:m9>=0.85", m9=r["m9_human_score"], weight=3.0)
        for r in rows
        if (r["text"] or "").strip()
    ]


async def fetch_long_en(dsn: str, limit: int) -> list[dict]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(SQL_LONG_EN, limit)
    finally:
        await conn.close()
    return [
        _row(r["text"] or "", source="coactor:long_en:m9>=0.85", m9=r["m9_human_score"], weight=3.0)
        for r in rows
        if (r["text"] or "").strip()
    ]


async def main_async(args: argparse.Namespace) -> int:
    samples: list[dict] = []
    for t in USER_TEXTS:
        samples.append(_row(t, source="user_pinned", m9=None, weight=args.user_weight))

    settings = get_settings()
    if settings.coactor_database_url and args.coactor_count > 0:
        dsn = settings.coactor_database_url.replace("postgresql+asyncpg://", "postgresql://")
        try:
            ru_extra = await fetch_short_ru(dsn, args.coactor_count)
            en_extra = await fetch_long_en(dsn, args.coactor_count)
            samples.extend(ru_extra)
            samples.extend(en_extra)
        except Exception as exc:
            print(f"WARNING: failed to fetch from Co.Actor: {exc}", file=sys.stderr)

    seen: set[str] = set()
    deduped: list[dict] = []
    for s in samples:
        if s["text_hash"] in seen:
            continue
        seen.add(s["text_hash"])
        deduped.append(s)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(deduped).write_parquet(output)

    user_n = sum(1 for s in deduped if s["source"] == "user_pinned")
    coactor_ru = sum(1 for s in deduped if s["source"] == "coactor:short_ru:m9>=0.85")
    coactor_en = sum(1 for s in deduped if s["source"] == "coactor:long_en:m9>=0.85")
    print(f"Wrote {len(deduped)} pinned human samples to {output}")
    print(f"  user_pinned:        {user_n}  (weight={args.user_weight})")
    print(f"  coactor short RU:   {coactor_ru}  (weight=3.0)")
    print(f"  coactor long EN:    {coactor_en}  (weight=3.0)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/ground_truth/human_pinned.parquet")
    parser.add_argument("--user-weight", type=float, default=20.0)
    parser.add_argument("--coactor-count", type=int, default=15)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
