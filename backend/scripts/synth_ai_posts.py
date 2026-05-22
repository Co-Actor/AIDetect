"""Generate synthetic AI-authored posts via OpenRouter to balance the ground truth.

Topics × language × model × N variants → parquet with label='ai'. Models are
rotated so we don't overfit the detector to one provider's tells.

Usage:
    uv run python scripts/synth_ai_posts.py --output data/ground_truth/synthetic_ai_v1.parquet
    uv run python scripts/synth_ai_posts.py --variants 1 --models anthropic/claude-haiku-4-5
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from aidetect.config import get_settings


TOPICS_EN = [
    "lessons learned from a recent hiring mistake",
    "why your startup should ship slower",
    "remote-work culture in distributed teams",
    "what AI is changing for marketers in 2026",
    "the biggest founder mistake I almost made",
    "how to give honest performance feedback",
    "what I learned scaling from 5 to 50 people",
    "why most product roadmaps are wrong",
    "the case for boring technology choices",
    "how I structure my week as a CEO",
]

TOPICS_RU = [
    "что я узнал, нанимая первых сотрудников",
    "почему стартапу полезно замедлиться",
    "как мы перешли на удалёнку и что вышло",
    "что меняет ИИ в маркетинге в 2026 году",
    "ошибка, которую я едва не совершил, как фаундер",
]

STYLES = ["thoughtful", "personal-reflection", "tactical-tips", "contrarian-take"]

DEFAULT_MODELS = [
    "anthropic/claude-sonnet-4-6",
    "openai/gpt-4o",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
]


def make_prompt(topic: str, language: str, style: str) -> str:
    lang_label = "Russian" if language == "ru" else "English"
    return (
        f"Write a {style} LinkedIn post in {lang_label} about: {topic}. "
        f"Length 150-250 words. Engage the reader. Return ONLY the post text, "
        f"no preamble or commentary."
    )


async def call_one(
    client: httpx.AsyncClient, settings: Any, model: str, prompt: str, temperature: float
) -> str | None:
    body = {
        "model": model,
        "temperature": temperature,
        "max_tokens": 700,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aidetect.local",
        "X-Title": "AIDetect-synth",
    }
    try:
        resp = await client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  ! {model[:30]:30s}: {type(exc).__name__}: {str(exc)[:100]}", file=sys.stderr)
        return None


async def generate(
    settings: Any, models: list[str], variants: int, languages: list[str], concurrency: int
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    samples: list[dict] = []
    seen: set[str] = set()
    lock = asyncio.Lock()

    async def worker(client: httpx.AsyncClient, lang: str, topic: str, model: str, idx: int) -> None:
        style = STYLES[idx % len(STYLES)]
        prompt = make_prompt(topic, lang, style)
        async with sem:
            text = await call_one(client, settings, model, prompt, temperature=1.0)
        if not text:
            return
        text = text.strip()
        if len(text) < 80:
            return
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        async with lock:
            if h in seen:
                return
            seen.add(h)
            samples.append(
                {
                    "id": h[:16],
                    "text": text,
                    "text_hash": h,
                    "label": "ai",
                    "weight": 1.0,
                    "language": lang,
                    "platform": "linkedin",
                    "source": f"synth:{model}",
                    "created_at": None,
                    "length_chars": len(text),
                }
            )

    tasks: list[asyncio.Task] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for lang in languages:
            topics = TOPICS_EN if lang == "en" else TOPICS_RU
            for topic_i, topic in enumerate(topics):
                for model in models:
                    for v in range(variants):
                        tasks.append(
                            asyncio.create_task(
                                worker(client, lang, topic, model, topic_i * 7 + v)
                            )
                        )
        total = len(tasks)
        print(f"Dispatching {total} generations across {len(models)} models, "
              f"{len(languages)} langs, variants={variants}, concurrency={concurrency}...")
        done = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            if done % 20 == 0 or done == total:
                print(f"  {done}/{total} done — collected {len(samples)}")
    return samples


def write_parquet(samples: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(samples).write_parquet(output)


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.openrouter_api_key:
        print("ERROR: OPENROUTER_API_KEY not set in backend/.env", file=sys.stderr)
        return 1

    models = args.models.split(",") if args.models else DEFAULT_MODELS
    languages = args.languages.split(",")

    samples = await generate(
        settings=settings,
        models=models,
        variants=args.variants,
        languages=languages,
        concurrency=args.concurrency,
    )

    if not samples:
        print("ERROR: no samples generated", file=sys.stderr)
        return 1

    by_lang: dict[str, int] = {}
    by_model: dict[str, int] = {}
    for s in samples:
        by_lang[s["language"]] = by_lang.get(s["language"], 0) + 1
        by_model[s["source"]] = by_model.get(s["source"], 0) + 1
    print(f"\nGenerated {len(samples)} samples")
    print(f"  by language: {dict(sorted(by_lang.items()))}")
    print(f"  by model:    {dict(sorted(by_model.items()))}")

    if args.dry_run:
        print("--dry-run: not writing parquet.")
        return 0

    output = Path(args.output)
    write_parquet(samples, output)
    sidecar = output.with_suffix(output.suffix + ".meta.json")
    sidecar.write_text(
        json.dumps(
            {
                "models": models,
                "languages": languages,
                "variants": args.variants,
                "samples": len(samples),
                "by_language": by_lang,
                "by_model": by_model,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"Wrote {len(samples)} samples to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/ground_truth/synthetic_ai_v1.parquet")
    parser.add_argument("--models", default=None, help="comma-separated OpenRouter model ids")
    parser.add_argument("--languages", default="en,ru")
    parser.add_argument("--variants", type=int, default=2, help="variants per (lang, topic, model)")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
