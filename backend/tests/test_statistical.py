from __future__ import annotations

import pytest

from aidetect.services.signals.statistical import compute_statistical


HUMAN_TEXT = (
    "Last Tuesday I shipped a tiny config change. Nothing fancy. The kind of thing you don't "
    "even bother to write a ticket for. Three minutes later prod went down for nineteen "
    "minutes. Customers couldn't pay. Slack lit up. I felt sick. The fix was a one-line "
    "rollback. The lesson, of course, was bigger: I had stopped reading my own diffs. So I "
    "wrote a checklist. It's three lines. I've used it on every change since."
)

AI_TEXT = (
    "In today's fast-paced world, businesses must continuously adapt to thrive. "
    "Modern enterprises increasingly leverage cutting-edge technology to maintain competitiveness. "
    "Innovative organizations seamlessly integrate automation across operations. "
    "Successful companies relentlessly pursue groundbreaking strategies for sustainable growth. "
    "Industry leaders consistently demonstrate exceptional commitment to operational excellence."
)

REPETITIVE_TEXT = (
    "Five words in each one. Five words in each one. Five words in each one. "
    "Five words in each one. Five words in each one. Five words in each one."
)


@pytest.mark.asyncio
async def test_human_text_low_ai_score() -> None:
    sig = await compute_statistical(HUMAN_TEXT)
    assert sig.score < 0.45, f"human text should look human-ish, got AI score {sig.score}"
    contributors = sig.contributors
    assert contributors["burstiness"]["sd"] is not None
    assert contributors["ttr"]["ttr"] is not None
    assert contributors["sentence_cv"]["cv"] is not None


@pytest.mark.asyncio
async def test_repetitive_text_high_ai_score() -> None:
    sig = await compute_statistical(REPETITIVE_TEXT)
    assert sig.score > 0.6, (
        f"identical-length sentences should score AI-like, got AI score {sig.score}"
    )
    burst = sig.contributors["burstiness"]
    assert burst["sd"] == 0 or burst["sd"] < 1


@pytest.mark.asyncio
async def test_empty_text_neutral() -> None:
    sig = await compute_statistical("")
    assert sig.score == pytest.approx(0.5)
    assert sig.contributors["flag"] == "empty_text"


@pytest.mark.asyncio
async def test_short_human_post_does_not_get_penalised() -> None:
    """5-sentence micro-blog post on one topic — should score human."""
    text = (
        "I've been using /remote-control for a while now and honestly it's convenient.\n\n"
        "Run Claude Code from a terminal on the server and control it from a phone or laptop.\n\n"
        "Then they added Dispatch for Claude Cowork — you can start a session from mobile.\n\n"
        "And yesterday Channels for using Claude in a Telegram bot.\n\n"
        "All so we keep spinning these token slots."
    )
    sig = await compute_statistical(text)
    # Statistical AI should now stay under 0.20 thanks to the short-regime thresholds.
    assert sig.score < 0.25, f"short post over-flagged: AI={sig.score}"
    assert sig.contributors["regime"] in {"very_short", "short"}


@pytest.mark.asyncio
async def test_code_blocks_excluded_from_stats() -> None:
    text = (
        "Wrap it in @media (prefers-color-scheme: dark) and the browser handles the rest "
        "in real time. Or flip it. Three lines of CSS, and it works in 97%+ of browsers.\n\n"
        "```css\n"
        "img { filter: grayscale(100%); }\n"
        "img:hover { filter: grayscale(0); }\n"
        "```\n"
    )
    sig = await compute_statistical(text)
    pp = sig.contributors.get("preprocessing")
    assert pp is not None
    assert pp["code_ratio"] > 0.15  # fenced block was stripped
    assert pp["fell_back_to_raw"] is False


@pytest.mark.asyncio
async def test_unicode_bold_and_emdash_penalised() -> None:
    sig = await compute_statistical(
        "𝐓𝐡𝐢𝐬 𝐢𝐬 𝐔𝐧𝐢𝐜𝐨𝐝𝐞 𝐛𝐨𝐥𝐝 — and lots of em-dashes — like — these — and — more — and — yet — more."
    )
    fmt = sig.contributors["formatting"]
    assert fmt["has_unicode_bold"] is True
    assert fmt["emdash_count"] >= 6
    assert "unicode_bold_chars" in fmt["flags"]
    assert "em_dash_overuse" in fmt["flags"]
