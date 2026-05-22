"""Layer C: rubric-driven LLM judge via OpenRouter.

Returns AI-likeness score (0..1) plus per-dimension rubric scores. If the
OpenRouter key is not configured or the API errors out, the judge degrades
gracefully to a neutral 0.5 with an explanatory error message.
"""
from __future__ import annotations

import contextlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import tenacity
import yaml

from aidetect.config import Settings
from aidetect.schemas.detection import LLMJudgeSignal, RubricDimensionScore, SentenceScore
from aidetect.services.signals.statistical import _SENT_SPLIT_RE

logger = logging.getLogger(__name__)

_PROMPTS_PATH_TPL = Path(__file__).resolve().parents[2] / "rubric" / "{ver}" / "prompts.yaml"
_TRUNCATE_TO = 6000  # ~1500 tokens
_TIMEOUT = 20.0
_NEUTRAL_SCORE = 0.5
_MAX_SENTENCES = 25
_MIN_SENT_CHARS = 12
_BLEND_WEIGHT_HOLISTIC = 0.5  # final llm_score = blend * holistic + (1-blend) * sentence_mean


@lru_cache(maxsize=4)
def _load_prompts(version: str) -> dict[str, Any]:
    path = Path(str(_PROMPTS_PATH_TPL).format(ver=version))
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _truncate(text: str, limit: int = _TRUNCATE_TO) -> str:
    if len(text) <= limit:
        return text
    half = (limit - 60) // 2
    return f"{text[:half]}\n[... truncated {len(text) - 2 * half} chars ...]\n{text[-half:]}"


def _build_user_message(text: str, dimensions: list[dict[str, Any]], instructions: str) -> str:
    rubric_block = "\n".join(
        f"- {d['id']} (weight {d['weight']}): {d['check']}" for d in dimensions
    )
    return (
        f"{instructions.strip()}\n\n"
        f"RUBRIC DIMENSIONS:\n{rubric_block}\n\n"
        f"=== TEXT TO ANALYZE ===\n{_truncate(text)}\n=== END OF TEXT ==="
    )


def _build_json_schema(dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    # NOTE: Bedrock-routed providers reject `minimum/maximum` on number fields.
    # We clamp post-parse in `_aggregate` instead.
    dim_props = {
        d["id"]: {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "evidence": {"type": "string"},
            },
            "required": ["score", "evidence"],
            "additionalProperties": False,
        }
        for d in dimensions
    }
    return {
        "name": "ai_detection_rubric",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "object",
                    "properties": dim_props,
                    "required": [d["id"] for d in dimensions],
                    "additionalProperties": False,
                },
                "summary": {"type": "string"},
            },
            "required": ["scores", "summary"],
            "additionalProperties": False,
        },
    }


def _parse_content(content: str) -> dict[str, Any]:
    """Parse JSON from message content; tolerate ```json fences."""
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    return json.loads(s)


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=4),
    stop=tenacity.stop_after_attempt(2),
    retry=tenacity.retry_if_exception_type(
        (httpx.NetworkError, httpx.TimeoutException)
    ),
    reraise=True,
)
async def _call_openrouter(
    settings: Settings, model: str, system_prompt: str, user_prompt: str, schema: dict[str, Any]
) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aidetect.local",
        "X-Title": "AIDetect",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


def _aggregate(
    parsed: dict[str, Any], dimensions: list[dict[str, Any]]
) -> tuple[float, dict[str, RubricDimensionScore]]:
    scores_in = parsed.get("scores") or {}
    weights = {d["id"]: float(d["weight"]) for d in dimensions}
    total_w = 0.0
    weighted = 0.0
    rubric: dict[str, RubricDimensionScore] = {}
    for d_id, w in weights.items():
        item = scores_in.get(d_id)
        if not isinstance(item, dict):
            continue
        try:
            s = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        s = max(0.0, min(1.0, s))
        rubric[d_id] = RubricDimensionScore(score=s, evidence=item.get("evidence"))
        weighted += s * w
        total_w += w
    human_score = weighted / total_w if total_w > 0 else _NEUTRAL_SCORE
    ai_score = max(0.0, min(1.0, 1.0 - human_score))
    return ai_score, rubric


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]


def _select_sentences(sentences: list[str], limit: int = _MAX_SENTENCES) -> list[str]:
    """Return up to `limit` sentences, dropping noise and fitting middle-out if too many."""
    cleaned = [s for s in sentences if len(s) >= _MIN_SENT_CHARS]
    if len(cleaned) <= limit:
        return cleaned
    half = limit // 2
    return cleaned[:half] + cleaned[-(limit - half):]


def _build_sentence_user_message(sentences: list[str], instructions: str) -> str:
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    return f"{instructions.strip()}\n\nSENTENCES:\n{numbered}"


def _build_sentence_schema(num_sentences: int) -> dict[str, Any]:
    # NOTE: Bedrock-routed providers reject minItems/maxItems > 1 on arrays —
    # length is enforced post-parse in `_aggregate_sentence_scores`.
    return {
        "name": "sentence_judge",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "sentences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "i": {"type": "integer"},
                            "score": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["i", "score", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["sentences"],
            "additionalProperties": False,
        },
    }


def _aggregate_sentence_scores(
    parsed: dict[str, Any], sentences: list[str]
) -> tuple[list[SentenceScore], dict[str, float]] | None:
    items = parsed.get("sentences")
    if not isinstance(items, list):
        return None
    by_idx: dict[int, dict[str, Any]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            idx = int(it.get("i"))
            score = float(it.get("score"))
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(sentences):
            by_idx[idx] = {"score": score, "reason": it.get("reason")}

    import statistics as _stats

    out: list[SentenceScore] = []
    ai_scores: list[float] = []
    for i, text in enumerate(sentences, start=1):
        item = by_idx.get(i)
        if item is None:
            continue
        # Convert human-likeness 0..1 to AI-likeness for downstream blending.
        ai = max(0.0, min(1.0, 1.0 - item["score"]))
        out.append(
            SentenceScore(
                index=i,
                text=text,
                score=round(ai, 4),
                reason=item.get("reason"),
            )
        )
        ai_scores.append(ai)
    if not ai_scores:
        return None
    aggregate = {
        "count": len(ai_scores),
        "mean": round(sum(ai_scores) / len(ai_scores), 4),
        "median": round(_stats.median(ai_scores), 4),
        "max": round(max(ai_scores), 4),
        "fraction_ai_like": round(sum(1 for x in ai_scores if x >= 0.5) / len(ai_scores), 4),
    }
    return out, aggregate


async def _run_holistic(
    settings: Settings, text: str, mode: str, trace: Any | None = None
) -> tuple[float, dict[str, RubricDimensionScore], str | None, str | None, dict[str, int] | None]:
    model = settings.model_for_mode(mode)
    prompts = _load_prompts(settings.rubric_version)
    system_prompt = (prompts.get("system") or "").strip()
    dimensions = list(prompts.get("rubric_dimensions") or [])
    instructions = (prompts.get("instructions") or "").strip()
    if not system_prompt or not dimensions or not instructions:
        return _NEUTRAL_SCORE, {}, None, "rubric/v*/prompts.yaml incomplete (holistic)", None

    user_prompt = _build_user_message(text, dimensions, instructions)
    schema = _build_json_schema(dimensions)

    # Open a Langfuse generation for this OpenRouter call so the
    # provider, prompt, output and token usage show up under the
    # detection trace. When tracing is disabled `trace` is a _NoopTrace
    # and .generation()/.end() are cheap no-ops.
    generation = None
    if trace is not None:
        try:
            generation = trace.generation(
                name="llm_judge.holistic",
                model=model,
                input={"system": system_prompt, "user": user_prompt},
                metadata={"mode": mode, "rubric_version": settings.rubric_version},
            )
        except Exception:  # observability never breaks the request
            generation = None

    try:
        raw = await _call_openrouter(settings, model, system_prompt, user_prompt, schema)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "[llm_judge:holistic] HTTP %s: %s", exc.response.status_code, exc.response.text[:300]
        )
        _end_generation(generation, output=None, level="ERROR",
                        status_message=f"HTTP {exc.response.status_code}")
        return _NEUTRAL_SCORE, {}, None, f"OpenRouter HTTP {exc.response.status_code}", None
    except httpx.HTTPError as exc:
        logger.warning("[llm_judge:holistic] %s", exc)
        _end_generation(generation, output=None, level="ERROR",
                        status_message=exc.__class__.__name__)
        return _NEUTRAL_SCORE, {}, None, f"network: {exc.__class__.__name__}", None
    try:
        content = raw["choices"][0]["message"]["content"]
        parsed = _parse_content(content)
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        _end_generation(generation, output=None, level="ERROR",
                        status_message=f"unparsable: {exc.__class__.__name__}")
        return _NEUTRAL_SCORE, {}, None, f"unparsable: {exc.__class__.__name__}", None

    ai_score, rubric = _aggregate(parsed, dimensions)
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), str) else None
    usage = _extract_usage(raw.get("usage"))
    _end_generation(generation, output=parsed, usage=usage)
    return ai_score, rubric, summary, None, usage


def _extract_usage(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, int] = {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = raw.get(k)
        if isinstance(v, int):
            out[k] = v
    return out or None


def _end_generation(
    generation: Any | None,
    *,
    output: Any | None,
    usage: dict[str, int] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    """Finalise a Langfuse generation, ignoring all errors.

    Maps OpenRouter usage keys to Langfuse's `usage_details` (input/output/total)
    so cost dashboards work out of the box.
    """
    if generation is None:
        return
    kwargs: dict[str, Any] = {"output": output}
    if usage:
        usage_details: dict[str, int] = {}
        if "prompt_tokens" in usage:
            usage_details["input"] = usage["prompt_tokens"]
        if "completion_tokens" in usage:
            usage_details["output"] = usage["completion_tokens"]
        if "total_tokens" in usage:
            usage_details["total"] = usage["total_tokens"]
        if usage_details:
            kwargs["usage_details"] = usage_details
    if level is not None:
        kwargs["level"] = level
    if status_message is not None:
        kwargs["status_message"] = status_message
    with contextlib.suppress(Exception):
        generation.end(**kwargs)


async def _run_sentence(
    settings: Settings, text: str, mode: str, trace: Any | None = None
) -> tuple[
    list[SentenceScore] | None, dict[str, float] | None, str | None, dict[str, int] | None
]:
    model = settings.model_for_mode(mode)
    prompts = _load_prompts(settings.rubric_version)
    sect = prompts.get("sentence_judge") or {}
    system_prompt = (sect.get("system") or "").strip()
    instructions = (sect.get("instructions") or "").strip()
    if not system_prompt or not instructions:
        return None, None, "sentence_judge prompt missing", None

    sentences = _select_sentences(_split_sentences(text))
    if len(sentences) < 3:
        return None, None, "too few sentences for sentence-level judge", None

    user_prompt = _build_sentence_user_message(sentences, instructions)
    schema = _build_sentence_schema(len(sentences))

    generation = None
    if trace is not None:
        try:
            generation = trace.generation(
                name="llm_judge.sentence",
                model=model,
                input={"system": system_prompt, "user": user_prompt},
                metadata={
                    "mode": mode,
                    "rubric_version": settings.rubric_version,
                    "sentence_count": len(sentences),
                },
            )
        except Exception:
            generation = None

    try:
        raw = await _call_openrouter(settings, model, system_prompt, user_prompt, schema)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "[llm_judge:sent] HTTP %s: %s", exc.response.status_code, exc.response.text[:300]
        )
        _end_generation(generation, output=None, level="ERROR",
                        status_message=f"HTTP {exc.response.status_code}")
        return None, None, f"sentence: OpenRouter HTTP {exc.response.status_code}", None
    except httpx.HTTPError as exc:
        logger.warning("[llm_judge:sent] %s", exc)
        _end_generation(generation, output=None, level="ERROR",
                        status_message=exc.__class__.__name__)
        return None, None, f"sentence: network: {exc.__class__.__name__}", None
    try:
        content = raw["choices"][0]["message"]["content"]
        parsed = _parse_content(content)
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        _end_generation(generation, output=None, level="ERROR",
                        status_message=f"unparsable: {exc.__class__.__name__}")
        return None, None, f"sentence: unparsable: {exc.__class__.__name__}", None

    res = _aggregate_sentence_scores(parsed, sentences)
    if res is None:
        _end_generation(generation, output=parsed, level="WARNING",
                        status_message="empty aggregate")
        return None, None, "sentence: empty aggregate", None
    sentence_scores, aggregate = res
    usage = _extract_usage(raw.get("usage"))
    _end_generation(generation, output={"aggregate": aggregate}, usage=usage)
    return sentence_scores, aggregate, None, usage


async def compute_llm_judge(
    text: str, mode: str, settings: Settings, trace: Any | None = None
) -> LLMJudgeSignal:
    model = settings.model_for_mode(mode)

    if not settings.openrouter_api_key:
        return LLMJudgeSignal(
            score=_NEUTRAL_SCORE,
            model="(disabled)",
            summary=None,
            error="OPENROUTER_API_KEY not configured — LLM judge skipped",
        )

    if not text or not text.strip():
        return LLMJudgeSignal(
            score=_NEUTRAL_SCORE, model=model, summary=None, error="empty text"
        )

    import asyncio as _asyncio

    if mode == "fast":
        ai_score, rubric, summary, error, usage = await _run_holistic(
            settings, text, mode, trace=trace
        )
        return LLMJudgeSignal(
            score=round(ai_score, 4),
            model=model,
            summary=summary,
            rubric_scores=rubric or None,
            error=error,
            usage=usage,
        )

    holistic_task = _asyncio.create_task(_run_holistic(settings, text, mode, trace=trace))
    sentence_task = _asyncio.create_task(_run_sentence(settings, text, mode, trace=trace))
    holistic_result, sentence_result = await _asyncio.gather(holistic_task, sentence_task)

    ai_score, rubric, summary, h_error, h_usage = holistic_result
    sentence_scores, aggregate, s_error, s_usage = sentence_result

    blended = ai_score
    if aggregate is not None:
        # Use median of sentence scores — robust to a single outlier sentence
        # (e.g. a satirical one-liner that the model over-flags as AI).
        sent_centre = aggregate.get("median", aggregate["mean"])
        blended = _BLEND_WEIGHT_HOLISTIC * ai_score + (1.0 - _BLEND_WEIGHT_HOLISTIC) * sent_centre

    error_parts = [e for e in (h_error, s_error) if e]
    error_msg = "; ".join(error_parts) if error_parts else None

    combined_usage: dict[str, int] | None = None
    for u in (h_usage, s_usage):
        if not u:
            continue
        combined_usage = combined_usage or {}
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            v = u.get(k)
            if isinstance(v, int):
                combined_usage[k] = combined_usage.get(k, 0) + v

    return LLMJudgeSignal(
        score=round(max(0.0, min(1.0, blended)), 4),
        model=model,
        summary=summary,
        rubric_scores=rubric or None,
        error=error_msg,
        sentence_scores=sentence_scores,
        sentence_aggregate=aggregate,
        usage=combined_usage,
    )
