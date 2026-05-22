"""Layer B: pattern matching driven by rubric/v1/patterns.yaml.

Two kinds of detections produce one combined PatternsSignal:

  Phrase matches: lowercase substring or word-boundary scan of the rubric registry,
                  filtered by detected language.
  Structure matches: rule-based detectors (regex_in_tail, count_threshold, regex_present)
                  that flag formatting tells (bookend summary, em-dash overuse, etc.).

Score = sum(severity_weight) capped at 1.0. Higher score = more AI-like.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from aidetect.schemas.detection import PatternMatch, PatternsSignal, Severity

_RUBRIC_DIR = Path(__file__).resolve().parents[2] / "rubric"

SEVERITY_WEIGHT: dict[str, float] = {"low": 0.05, "medium": 0.10, "high": 0.20}


@dataclass(frozen=True)
class _Phrase:
    phrase: str
    severity: Severity
    suggestion: str | None
    languages: tuple[str, ...]
    category: str
    source: str
    word_boundary: bool

    @property
    def regex(self) -> re.Pattern[str]:
        return _phrase_regex(self.phrase, self.word_boundary)


@dataclass(frozen=True)
class _Structure:
    id: str
    description: str
    severity: Severity
    detection: dict[str, Any]
    source: str


@lru_cache(maxsize=8)
def _phrase_regex(phrase: str, word_boundary: bool) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    if word_boundary and phrase[0].isalnum() and phrase[-1].isalnum():
        return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE | re.UNICODE)
    return re.compile(escaped, re.IGNORECASE | re.UNICODE)


@lru_cache(maxsize=4)
def _load_rubric(version: str) -> tuple[tuple[_Phrase, ...], tuple[_Structure, ...]]:
    path = _RUBRIC_DIR / version / "patterns.yaml"
    if not path.exists():
        return (), ()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    phrases: list[_Phrase] = []
    for raw in data.get("banned_phrases", []) or []:
        languages = tuple(raw.get("languages") or ["en"])
        phrases.append(
            _Phrase(
                phrase=str(raw["phrase"]).lower(),
                severity=str(raw.get("severity", "medium")),  # type: ignore[arg-type]
                suggestion=raw.get("suggestion"),
                languages=languages,
                category=str(raw.get("category", "verb_cliche")),
                source=str(raw.get("source", "")),
                word_boundary=bool(raw.get("word_boundary", True)),
            )
        )

    structures: list[_Structure] = []
    for raw in data.get("structures", []) or []:
        structures.append(
            _Structure(
                id=str(raw["id"]),
                description=str(raw.get("description", "")),
                severity=str(raw.get("severity", "medium")),  # type: ignore[arg-type]
                detection=dict(raw.get("detection") or {}),
                source=str(raw.get("source", "")),
            )
        )
    return tuple(phrases), tuple(structures)


def _language_matches(detected: str | None, allowed: tuple[str, ...]) -> bool:
    if not allowed:
        return True
    if detected in (None, "auto", "unknown"):
        return True
    return detected in allowed


def _scan_phrases(
    text: str, phrases: tuple[_Phrase, ...], language: str | None
) -> list[PatternMatch]:
    matches: list[PatternMatch] = []
    seen: set[tuple[str, int, int]] = set()
    for ph in phrases:
        if not _language_matches(language, ph.languages):
            continue
        for m in ph.regex.finditer(text):
            key = (ph.phrase, m.start(), m.end())
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                PatternMatch(
                    category=f"phrase:{ph.category}",
                    name=ph.phrase,
                    span=(m.start(), m.end()),
                    severity=ph.severity,
                    suggestion=ph.suggestion,
                )
            )
    return matches


def _count_emoji(text: str) -> int:
    from aidetect.services.signals.statistical import _EMOJI_RE  # local import to avoid cycle

    return len(_EMOJI_RE.findall(text))


def _count_emdash(text: str) -> int:
    return text.count("—")


def _count_bold_md(text: str) -> int:
    return len(re.findall(r"\*\*[^*\n]+\*\*|__[^_\n]+__", text))


def _count_hashtag(text: str) -> int:
    return len(re.findall(r"(?<!\w)#[\wЀ-ӿ]+", text, re.UNICODE))


_COUNTERS = {
    "emoji": _count_emoji,
    "emdash": _count_emdash,
    "bold_md": _count_bold_md,
    "hashtag": _count_hashtag,
}


_BULLET_RE = re.compile(r"^\s*(?:[•*\-–—‣◦]|\d+[.)])\s+(.+?)\s*$")
_BULLET_PREFIX_RE = re.compile(
    r"^([\wЀ-ӿ]+(?:\s+[\wЀ-ӿ]+){0,2})\s*[:—–-]",
    re.UNICODE,
)


def _last_sentence(text: str) -> tuple[str, int] | None:
    """Return (sentence, start_offset_in_text) of the last non-empty sentence."""
    from aidetect.services.signals.statistical import _SENT_SPLIT_RE

    parts = _SENT_SPLIT_RE.split(text)
    for part in reversed(parts):
        s = part.strip()
        if s:
            start = text.rfind(s)
            return s, max(0, start)
    return None


def _detect_parallel_bullets(text: str, min_items: int) -> tuple[int, int] | None:
    """Find a run of >= min_items bullets with parallel openings.

    A "parallel opening" is one of:
      - same first noun-like prefix followed by ':' / '—' (e.g. 'Default state:', 'Hover state:'),
      - same first verb / function token (e.g. 'Use ...', 'Use ...', 'Use ...').

    Returns the (start, end) span covering the parallel run, or None.
    """
    lines = text.splitlines(keepends=True)
    bullets: list[tuple[int, int, str]] = []  # (line_idx, char_offset, content)
    cursor = 0
    for line in lines:
        m = _BULLET_RE.match(line)
        if m:
            bullets.append((len(bullets), cursor, m.group(1)))
        cursor += len(line)

    if len(bullets) < min_items:
        return None

    # Walk through bullets; collect the longest run of consecutive bullets that
    # share an opening pattern.
    best_run: list[tuple[int, int, str]] = []
    current: list[tuple[int, int, str]] = []

    def opening_key(content: str) -> str:
        # 1) explicit "Word: ..." or "Word — ..." style prefix
        m = _BULLET_PREFIX_RE.match(content)
        if m:
            return f"prefix:{m.group(1).lower()}"
        # 2) starts with a capitalised word that looks like the start of a
        #    noun-phrase: "Unnecessary re-renders…", "Incorrect state…", "Lack of…"
        first_words = content.split(maxsplit=1)
        if first_words and first_words[0][:1].isupper() and first_words[0][:1].isalpha():
            return "cap_noun"
        if first_words:
            return f"first:{first_words[0].lower()}"
        return ""

    keys = [opening_key(c) for _, _, c in bullets]
    for i, b in enumerate(bullets):
        if not current:
            current = [b]
            continue
        prev_key = keys[i - 1]
        cur_key = keys[i]
        # Treat empty keys as non-parallel.
        if prev_key and cur_key and (
            prev_key == cur_key
            or (prev_key.startswith("prefix:") and cur_key.startswith("prefix:"))
            or (prev_key == "cap_noun" and cur_key == "cap_noun")
        ):
            current.append(b)
        else:
            if len(current) > len(best_run):
                best_run = current
            current = [b]
    if len(current) > len(best_run):
        best_run = current

    if len(best_run) < min_items:
        return None

    start = best_run[0][1]
    last_idx, last_off, last_content = best_run[-1]
    end = last_off + lines[last_idx].rstrip("\n").__len__()
    return start, end


def _scan_structures(
    text: str, structures: tuple[_Structure, ...]
) -> list[PatternMatch]:
    matches: list[PatternMatch] = []
    text_len = len(text)
    for st in structures:
        det_type = st.detection.get("type")
        if det_type == "regex_in_tail":
            tail_chars = int(st.detection.get("tail_chars", 240))
            tail_start = max(0, text_len - tail_chars)
            tail = text[tail_start:]
            for pat in st.detection.get("patterns", []) or []:
                m = re.search(pat, tail)
                if m:
                    matches.append(
                        PatternMatch(
                            category=f"structure:{st.id}",
                            name=st.id,
                            span=(tail_start + m.start(), tail_start + m.end()),
                            severity=st.severity,
                            suggestion=st.description,
                        )
                    )
                    break
        elif det_type == "count_threshold":
            counter = st.detection.get("counter")
            threshold = int(st.detection.get("threshold", 0))
            if counter not in _COUNTERS:
                continue
            value = _COUNTERS[counter](text)
            if value > threshold:
                matches.append(
                    PatternMatch(
                        category=f"structure:{st.id}",
                        name=st.id,
                        span=(0, min(text_len, 1)),
                        severity=st.severity,
                        suggestion=f"{st.description} (observed {value}, threshold {threshold})",
                    )
                )
        elif det_type == "regex_present":
            for pat in st.detection.get("patterns", []) or []:
                m = re.search(pat, text)
                if m:
                    matches.append(
                        PatternMatch(
                            category=f"structure:{st.id}",
                            name=st.id,
                            span=(m.start(), m.end()),
                            severity=st.severity,
                            suggestion=st.description,
                        )
                    )
                    break
        elif det_type == "regex_in_last_sentence":
            ls = _last_sentence(text)
            if ls is None:
                continue
            sent, sent_start = ls
            for pat in st.detection.get("patterns", []) or []:
                m = re.search(pat, sent)
                if m:
                    matches.append(
                        PatternMatch(
                            category=f"structure:{st.id}",
                            name=st.id,
                            span=(sent_start + m.start(), sent_start + m.end()),
                            severity=st.severity,
                            suggestion=st.description,
                        )
                    )
                    break
        elif det_type == "parallel_bullets":
            min_items = int(st.detection.get("min_items", 3))
            span = _detect_parallel_bullets(text, min_items)
            if span:
                matches.append(
                    PatternMatch(
                        category=f"structure:{st.id}",
                        name=st.id,
                        span=span,
                        severity=st.severity,
                        suggestion=st.description,
                    )
                )
    return matches


def _score_from_matches(matches: list[PatternMatch]) -> float:
    total = 0.0
    for m in matches:
        total += SEVERITY_WEIGHT.get(m.severity, 0.10)
    return min(1.0, round(total, 4))


async def compute_patterns(
    text: str, rubric_version: str = "v1", language: str | None = None
) -> PatternsSignal:
    if not text:
        return PatternsSignal(score=0.0, matches=[])
    phrases, structures = _load_rubric(rubric_version)
    matches: list[PatternMatch] = []
    matches.extend(_scan_phrases(text, phrases, language))
    matches.extend(_scan_structures(text, structures))
    matches.sort(key=lambda m: m.span[0])
    return PatternsSignal(score=_score_from_matches(matches), matches=matches)
