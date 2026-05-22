from __future__ import annotations

import pytest

from aidetect.services.signals.patterns import compute_patterns


@pytest.mark.asyncio
async def test_english_phrase_hits() -> None:
    text = (
        "Let's dive into this game-changer. We leverage cutting-edge AI seamlessly. "
        "In conclusion, the future is bright."
    )
    sig = await compute_patterns(text, language="en")
    names = {m.name for m in sig.matches}
    assert "dive into" in names
    assert "game-changer" in names
    assert "leverage" in names
    assert "cutting-edge" in names
    assert "seamlessly" in names
    assert "in conclusion" in names
    assert "the future is bright" in names
    assert sig.score > 0.5


@pytest.mark.asyncio
async def test_russian_phrase_hits() -> None:
    text = (
        "В современном мире давайте погрузимся в инновационный подход. "
        "Раскройте свой потенциал. Надеюсь, это поможет."
    )
    sig = await compute_patterns(text, language="ru")
    names = {m.name for m in sig.matches}
    assert "в современном мире" in names
    assert "давайте погрузимся" in names
    assert "инновационн" in names
    assert "раскройте свой потенциал" in names
    assert "надеюсь, это поможет" in names
    assert sig.score >= 0.5


@pytest.mark.asyncio
async def test_word_boundary_avoids_false_positives() -> None:
    sig = await compute_patterns("I am a relevant developer.", language="en")
    names = {m.name for m in sig.matches}
    assert "delve" not in names, "'relevant' must not match 'delve' (would be substring)"


@pytest.mark.asyncio
async def test_language_filter_skips_other_language_phrases() -> None:
    en_text = "Just a clean english sentence with nothing special."
    sig_ru_only = await compute_patterns(en_text, language="ru")
    assert sig_ru_only.score == 0.0


@pytest.mark.asyncio
async def test_structure_bookend_summary() -> None:
    text = (
        "Here is the body of the post. Some content here, some more there.\n\n"
        "In conclusion, every project benefits from clarity and structure."
    )
    sig = await compute_patterns(text, language="en")
    structure_ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "bookend_summary" in structure_ids


@pytest.mark.asyncio
async def test_structure_em_dash_overuse() -> None:
    text = (
        "First — second — third — fourth — fifth — sixth — seventh — and that's how it goes."
    )
    sig = await compute_patterns(text, language="en")
    structure_ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "em_dash_overuse" in structure_ids


@pytest.mark.asyncio
async def test_structure_unicode_bold_high_severity() -> None:
    sig = await compute_patterns("Header: 𝐈𝐦𝐩𝐨𝐫𝐭𝐚𝐧𝐭 stuff inside.", language="en")
    structure_ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "unicode_bold_chars" in structure_ids
    high = [m for m in sig.matches if m.severity == "high" and m.name == "unicode_bold_chars"]
    assert high


@pytest.mark.asyncio
async def test_clean_text_has_zero_score() -> None:
    sig = await compute_patterns(
        "She arrived at six. The bus was late. We grabbed coffee and waited.",
        language="en",
    )
    assert sig.score == 0.0
    assert sig.matches == []


@pytest.mark.asyncio
async def test_signposting_announcement_detected() -> None:
    text = "I'll show you a clean way. Here's how it works: just one CSS line and you're done."
    sig = await compute_patterns(text, language="en")
    ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "signposting_announcement" in ids


@pytest.mark.asyncio
async def test_negative_parallelism_detected() -> None:
    text = "I don't think it's laziness — it's just the easier path most teams default to."
    sig = await compute_patterns(text, language="en")
    ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "negative_parallelism" in ids


@pytest.mark.asyncio
async def test_reverse_engagement_close_detected() -> None:
    text = (
        "We use CSS filters everywhere now. The result is faster pages and fewer assets.\n\n"
        "Do you reach for CSS filters for practical stuff like this, or mostly for visual effects?"
    )
    sig = await compute_patterns(text, language="en")
    ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "reverse_engagement_close" in ids


@pytest.mark.asyncio
async def test_parallel_bullet_list_detected() -> None:
    text = (
        "Three lines:\n"
        "- Default state: img { filter: grayscale(100%); }\n"
        "- Hover state: img:hover { filter: grayscale(0); }\n"
        "- Dark mode: @media (prefers-color-scheme: dark) { ... }\n"
    )
    sig = await compute_patterns(text, language="en")
    ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "parallel_bullet_list" in ids


@pytest.mark.asyncio
async def test_non_parallel_bullets_not_flagged() -> None:
    text = (
        "Some thoughts:\n"
        "- short note\n"
        "- another idea, written normally\n"
        "- and a final point about something else entirely\n"
    )
    sig = await compute_patterns(text, language="en")
    ids = {m.name for m in sig.matches if m.category.startswith("structure:")}
    assert "parallel_bullet_list" not in ids


@pytest.mark.asyncio
async def test_soft_markers_combined_score() -> None:
    text = (
        "Actually, the real question is what changes here. Essentially, fundamentally, "
        "the truth is most teams overengineer this."
    )
    sig = await compute_patterns(text, language="en")
    names = {m.name for m in sig.matches}
    assert "actually" in names
    assert "essentially" in names
    assert "the real question is" in names
    assert sig.score > 0.0
