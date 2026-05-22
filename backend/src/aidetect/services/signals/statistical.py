"""Layer A: statistical signals.

Ports the core formulas from Co.Actor's post_quality_evaluator.py (M6/M7/M8/M10)
and blends them into a single AI-likeness score for the orchestrator.

All sub-scores below are computed in HUMAN-likeness orientation (1.0 = human, 0.0 = AI),
because that's how Co.Actor expresses them. The final `score` returned in the
StatisticalSignal is inverted to AI-likeness so it lines up with patterns/llm_judge.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from aidetect.schemas.detection import StatisticalSignal

MIN_SENTENCES_FOR_VARIATION = 3
NEUTRAL = 0.5

TTR_LOW = 0.65

# Thresholds depend on text length: micro-posts can't reach burstiness/CV targets
# tuned for 200+ word essays, and their TTR is naturally high (few repeats).
# `ttr_high >= 1.0` disables the upper penalty entirely.
LENGTH_REGIMES: dict[str, dict[str, float]] = {
    "very_short": {"sd": 2.5, "ttr_high": 1.01, "ttr_width": 0.15, "cv": 0.20},
    "short":      {"sd": 4.5, "ttr_high": 0.92, "ttr_width": 0.15, "cv": 0.30},
    "normal":     {"sd": 8.0, "ttr_high": 0.85, "ttr_width": 0.15, "cv": 0.40},
}


def _length_regime(n_sentences: int, n_words: int) -> str:
    if n_sentences < 5 or n_words < 60:
        return "very_short"
    if n_sentences < 10 or n_words < 150:
        return "short"
    return "normal"

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n{2,}")
_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)

_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_BULLET_LINE_RE = re.compile(r"^\s*(?:[•*\-–—‣◦]|\d+[.)])\s+", re.MULTILINE)
_CSS_LIKE_LINE_RE = re.compile(r"^[^.\n]*\{[^}\n]*\}[\s;]*$", re.MULTILINE)
_DECL_LIKE_LINE_RE = re.compile(
    r"^[ \t]*[\w-]+\s*:\s*[^.\n]+;?\s*$", re.MULTILINE
)
_PUNCT_NOISE_RE = re.compile(r"[{}();<>=]+")


def _strip_code_for_stats(text: str) -> str:
    """Remove code/markup that would otherwise distort burstiness/TTR.

    Preserves natural-language content. Used only by Layer A — Layer B/C work
    on the raw text so phrase matching and LLM judging still see everything.
    """
    s = _FENCED_CODE_RE.sub(" ", text)
    s = _INLINE_CODE_RE.sub(" ", s)
    s = _URL_RE.sub(" ", s)
    s = _CSS_LIKE_LINE_RE.sub(" ", s)
    s = _DECL_LIKE_LINE_RE.sub(" ", s)
    s = _BULLET_LINE_RE.sub(" ", s)
    s = _PUNCT_NOISE_RE.sub(" ", s)
    return s.strip()

_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "☀-⛿"
    "✀-➿"
    "]"
)
_UNICODE_BOLD_RE = re.compile(r"[\U0001d400-\U0001d7ff]")
_MD_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")
_HASHTAG_RE = re.compile(r"(?<!\w)#[\wЀ-ӿ]+", re.UNICODE)


@dataclass(frozen=True)
class _Stats:
    sentence_count: int
    word_count: int
    sentence_lengths: list[int]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]


def _sentence_lengths(text: str) -> list[int]:
    return [len(s.split()) for s in _sentences(text) if s.split()]


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _burstiness_human(lengths: list[int], regime: str) -> tuple[float, dict[str, object]]:
    if len(lengths) < MIN_SENTENCES_FOR_VARIATION:
        return NEUTRAL, {"sd": None, "sentence_count": len(lengths), "flag": "too_few_sentences"}
    target = LENGTH_REGIMES[regime]["sd"]
    sd = statistics.stdev(lengths)
    score = min(1.0, sd / target)
    return score, {
        "sd": round(sd, 2),
        "sentence_count": len(lengths),
        "target_sd": target,
        "regime": regime,
        "human_score": round(score, 3),
    }


def _ttr_human(words: list[str], regime: str) -> tuple[float, dict[str, object]]:
    if not words:
        return NEUTRAL, {"ttr": None, "flag": "no_words"}
    cfg = LENGTH_REGIMES[regime]
    ttr_high = cfg["ttr_high"]
    width = cfg["ttr_width"]
    ttr = len(set(words)) / len(words)
    if TTR_LOW <= ttr <= ttr_high:
        score = 1.0
    elif ttr < TTR_LOW:
        score = max(0.0, ttr / TTR_LOW)
    elif ttr_high >= 1.0:
        score = 1.0  # upper penalty disabled
    else:
        score = max(0.0, 1.0 - (ttr - ttr_high) / width)
    return score, {
        "ttr": round(ttr, 4),
        "unique_words": len(set(words)),
        "total_words": len(words),
        "ttr_high": ttr_high,
        "regime": regime,
        "in_range": TTR_LOW <= ttr <= ttr_high,
        "human_score": round(score, 3),
    }


def _sentence_cv_human(lengths: list[int], regime: str) -> tuple[float, dict[str, object]]:
    if len(lengths) < MIN_SENTENCES_FOR_VARIATION:
        return NEUTRAL, {"cv": None, "sentence_count": len(lengths), "flag": "too_few_sentences"}
    target = LENGTH_REGIMES[regime]["cv"]
    mean_len = statistics.mean(lengths)
    if mean_len <= 0:
        return NEUTRAL, {"cv": None, "flag": "zero_mean"}
    sd = statistics.stdev(lengths)
    cv = sd / mean_len
    score = min(1.0, cv / target)
    return score, {
        "cv": round(cv, 4),
        "sd": round(sd, 2),
        "mean": round(mean_len, 2),
        "target_cv": target,
        "regime": regime,
        "human_score": round(score, 3),
    }


def _formatting_human(text: str) -> tuple[float, dict[str, object]]:
    """Penalise telltale AI formatting habits.

    Each violation counts 1 toward a penalty (max 5). Final score = 1 - violations/5.
    """
    bold_md = len(_MD_BOLD_RE.findall(text))
    emoji_count = len(_EMOJI_RE.findall(text))
    emdash_count = text.count("—")
    has_unicode_bold = bool(_UNICODE_BOLD_RE.search(text))
    hashtags = _HASHTAG_RE.findall(text)
    hashtag_count = len(hashtags)

    violations = 0
    flags: list[str] = []
    if bold_md > 3:
        violations += 1
        flags.append("excessive_bold_markdown")
    if emoji_count > 5:
        violations += 1
        flags.append("emoji_overload")
    if emdash_count > 5:
        violations += 1
        flags.append("em_dash_overuse")
    if has_unicode_bold:
        violations += 1
        flags.append("unicode_bold_chars")
    if hashtag_count >= 5:
        violations += 1
        flags.append("hashtag_block")

    score = max(0.0, 1.0 - violations / 5.0)
    return score, {
        "bold_md_count": bold_md,
        "emoji_count": emoji_count,
        "emdash_count": emdash_count,
        "has_unicode_bold": has_unicode_bold,
        "hashtag_count": hashtag_count,
        "violations": violations,
        "flags": flags,
        "human_score": round(score, 3),
    }


async def compute_statistical(text: str) -> StatisticalSignal:
    if not text or not text.strip():
        return StatisticalSignal(
            score=NEUTRAL,
            contributors={"flag": "empty_text"},
        )

    nl_text = _strip_code_for_stats(text)
    nl_chars = len(nl_text)
    raw_chars = len(text)
    code_ratio = round(1.0 - (nl_chars / raw_chars), 3) if raw_chars else 0.0
    nl_for_stats = nl_text if nl_chars >= 80 else text

    lengths = _sentence_lengths(nl_for_stats)
    words = _words(nl_for_stats)
    regime = _length_regime(len(lengths), len(words))

    burst_score, burst = _burstiness_human(lengths, regime)
    ttr_score, ttr = _ttr_human(words, regime)
    cv_score, cv = _sentence_cv_human(lengths, regime)
    fmt_score, fmt = _formatting_human(text)

    human_score = (burst_score + ttr_score + cv_score + fmt_score) / 4.0
    ai_score = round(1.0 - human_score, 4)

    return StatisticalSignal(
        score=ai_score,
        contributors={
            "human_score": round(human_score, 4),
            "regime": regime,
            "burstiness": burst,
            "ttr": ttr,
            "sentence_cv": cv,
            "formatting": fmt,
            "preprocessing": {
                "code_ratio": code_ratio,
                "natural_language_chars": nl_chars,
                "fell_back_to_raw": nl_chars < 80,
            },
        },
    )
