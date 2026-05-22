"""AI -> human rewriter.

Pipeline:
  1. Run /v1/detections logic to score the input (Layer A + B + C).
  2. If already below target — return as-is.
  3. Build a rewrite prompt that bundles:
       - the original text
       - the matched banned phrases + their suggestions
       - the top-N AI-like sentences with reasons (from sentence-level judge)
       - the requested voice preset
       - the "preserve" list (facts / numbers / code / urls)
  4. Call OpenRouter, parse strict-JSON output.
  5. Audit: re-run detection on the rewritten text.
  6. If still above target and we have iterations left → repeat step 3.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import tenacity
import yaml

from aidetect.config import Settings
from aidetect.schemas.detection import (
    DetectionRequest,
    DetectionResponse,
    DetectionResultBlock,
)
from aidetect.schemas.rewrite import (
    IterationDiagnostic,
    RewriteRequest,
    RewriteResponse,
    RewriteUsage,
)
from aidetect.services.observability import get_observer
from aidetect.services.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

_PROMPTS_PATH_TPL = Path(__file__).resolve().parents[1] / "rubric" / "{ver}" / "prompts.yaml"
_REWRITE_TIMEOUT = 45.0
_TOP_N_SENTENCES = 6


def _load_rewrite_prompts(version: str) -> dict[str, Any]:
    path = Path(str(_PROMPTS_PATH_TPL).format(ver=version))
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("rewrite") or {}


def _rewrite_schema() -> dict[str, Any]:
    return {
        "name": "rewriter",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "rewritten_text": {"type": "string"},
                "changes": {"type": "array", "items": {"type": "string"}},
                "preserved": {"type": "string"},
            },
            "required": ["rewritten_text", "changes", "preserved"],
            "additionalProperties": False,
        },
    }


def _strip_code_blocks_placeholders(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace fenced code, inline code and URLs with placeholders.

    The LLM is told to keep placeholders verbatim, and we restore them
    after the rewrite. This guarantees code / links survive untouched.
    """
    saved: list[tuple[str, str]] = []

    def _save(prefix: str, content: str) -> str:
        token = f"__AIDETECT_{prefix}_{len(saved)}__"
        saved.append((token, content))
        return token

    s = text
    s = re.sub(r"```[\s\S]*?```", lambda m: _save("CODE", m.group(0)), s)
    s = re.sub(r"`[^`\n]+`", lambda m: _save("INLINE", m.group(0)), s)
    s = re.sub(r"https?://\S+", lambda m: _save("URL", m.group(0)), s)
    return s, saved


def _restore_placeholders(text: str, saved: list[tuple[str, str]]) -> str:
    out = text
    for token, content in saved:
        out = out.replace(token, content)
    return out


def _select_top_sentences(detection: DetectionResponse, n: int) -> list[dict[str, Any]]:
    signals = detection.signals
    if signals is None or signals.llm_judge is None or signals.llm_judge.sentence_scores is None:
        return []
    scored = list(signals.llm_judge.sentence_scores)
    scored.sort(key=lambda s: -s.score)
    out: list[dict[str, Any]] = []
    for s in scored[:n]:
        out.append({"text": s.text, "ai_score": s.score, "reason": s.reason or ""})
    return out


def _select_matched_phrases(detection: DetectionResponse) -> list[dict[str, str]]:
    signals = detection.signals
    if signals is None or signals.patterns is None:
        return []
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for m in signals.patterns.matches:
        key = f"{m.category}:{m.name}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "category": m.category,
                "phrase": m.name,
                "suggestion": m.suggestion or "",
                "severity": m.severity,
            }
        )
    return out


def _build_user_prompt(
    text_with_placeholders: str,
    detection: DetectionResponse,
    voice_block: str,
    preserve_note: str,
    custom_voice: str | None,
) -> str:
    matches = _select_matched_phrases(detection)
    sentences = _select_top_sentences(detection, _TOP_N_SENTENCES)

    bullet_phrases = (
        "\n".join(
            f"  - \"{m['phrase']}\" ({m['category']}, {m['severity']}) → {m['suggestion']}"
            for m in matches
        )
        or "  (no banned phrases matched — focus on tone and structure)"
    )

    bullet_sentences = (
        "\n".join(
            f"  - [score {s['ai_score']:.2f}] \"{s['text']}\"\n    reason: {s['reason']}"
            for s in sentences
        )
        or "  (no specific sentences flagged)"
    )

    cur_ai = detection.result.ai_probability
    voice_section = voice_block or "Generic human writing voice."
    if custom_voice:
        voice_section = f"{voice_section}\n\nExtra author guidance:\n{custom_voice.strip()}"

    return (
        f"Current AI-probability: {cur_ai:.2f}\n\n"
        f"PRESERVE VERBATIM: {preserve_note}\n"
        f"Code blocks, inline code, and URLs have been replaced by tokens of the form\n"
        f"`__AIDETECT_CODE_N__`, `__AIDETECT_INLINE_N__`, `__AIDETECT_URL_N__`.\n"
        f"Keep those tokens unchanged in your output — they will be restored after.\n\n"
        f"TARGET VOICE:\n{voice_section}\n\n"
        f"BANNED PHRASES TO REMOVE / REPLACE:\n{bullet_phrases}\n\n"
        f"AI-LIKE SENTENCES TO REWRITE:\n{bullet_sentences}\n\n"
        f"=== ORIGINAL TEXT ===\n{text_with_placeholders}\n=== END ==="
    )


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=4),
    stop=tenacity.stop_after_attempt(2),
    retry=tenacity.retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException)),
    reraise=True,
)
async def _call_rewriter(
    settings: Settings,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0.5,
        "max_tokens": 4000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_schema", "json_schema": _rewrite_schema()},
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aidetect.local",
        "X-Title": "AIDetect-rewriter",
    }
    async with httpx.AsyncClient(timeout=_REWRITE_TIMEOUT) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


def _parse_content(content: str) -> dict[str, Any]:
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    return json.loads(s)


def _verdict_from_detection(det: DetectionResponse) -> str:
    return det.result.verdict


def _end_gen(
    generation: Any | None,
    *,
    output: Any | None,
    usage: dict[str, int] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    """Finalise a Langfuse generation; safe to call with None or on errors."""
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


async def _detect(orchestrator: Orchestrator, text: str, mode: str) -> DetectionResponse:
    req = DetectionRequest(
        text=text,
        mode=mode,  # type: ignore[arg-type]
        options={  # type: ignore[arg-type]
            "include_signals": True,
            "include_evidence": False,
            "include_rubric_scores": False,
            "chunk_strategy": "auto",
        },
    )
    return await orchestrator.run(req, idempotency_key=None)


class Rewriter:
    def __init__(self, settings: Settings, orchestrator: Orchestrator) -> None:
        self.settings = settings
        self.orchestrator = orchestrator

    async def rewrite(self, req: RewriteRequest) -> RewriteResponse:
        started = time.perf_counter()
        if not self.settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")

        prompts = _load_rewrite_prompts(self.settings.rubric_version)
        system_prompt: str = (prompts.get("system") or "").strip()
        voices: dict[str, str] = prompts.get("voices") or {}
        if not system_prompt:
            raise RuntimeError(
                f"rubric/{self.settings.rubric_version}/prompts.yaml has no 'rewrite' section"
            )

        model = self.settings.model_for_mode(req.mode)
        voice_block = voices.get(req.options.voice or "", "") if req.options.voice else ""
        preserve_note = ", ".join(req.options.preserve)

        # Single Langfuse trace per /v1/rewrite — every iteration's OpenRouter
        # call attaches a nested generation, and we record before/after
        # ai_probability in the final trace.update().
        observer = get_observer()
        text_hash = hashlib.sha256(req.text.encode("utf-8")).hexdigest()
        trace = observer.start_rewrite_trace(
            text_hash=text_hash,
            mode=req.mode,
            voice=req.options.voice,
            target_ai=req.options.target_ai_probability,
            max_iterations=req.options.max_iterations,
        )

        before_det = await _detect(self.orchestrator, req.text, req.mode)
        iterations: list[IterationDiagnostic] = [
            IterationDiagnostic(
                index=0,
                ai_probability=before_det.result.ai_probability,
                verdict=_verdict_from_detection(before_det),
                summary="initial",
            )
        ]
        before_block = before_det.result

        # Already good enough — no work needed.
        if before_det.result.ai_probability <= req.options.target_ai_probability:
            return RewriteResponse(
                id=uuid.uuid4(),
                created_at=datetime.now(UTC),
                rewritten_text=req.text,
                changes=[],
                preserved_note="No rewrite needed — text already below target AI-probability.",
                before=before_block,
                after=before_block,
                iterations=iterations,
                target_reached=True,
                voice=req.options.voice,
                model=model,
                duration_ms=int((time.perf_counter() - started) * 1000),
                usage=RewriteUsage(),
                severity=before_block.severity,
            )

        current_text = req.text
        current_det = before_det
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        all_changes: list[str] = []
        preserved_note_out: str | None = None

        for i in range(1, req.options.max_iterations + 1):
            placeholders_text, saved = _strip_code_blocks_placeholders(current_text)
            user_prompt = _build_user_prompt(
                placeholders_text,
                current_det,
                voice_block,
                preserve_note,
                req.custom_voice_instructions,
            )

            generation: Any = None
            try:
                generation = trace.generation(
                    name=f"rewriter.iter_{i}",
                    model=model,
                    input={"system": system_prompt, "user": user_prompt},
                    metadata={
                        "iteration": i,
                        "current_ai_probability": current_det.result.ai_probability,
                        "target": req.options.target_ai_probability,
                    },
                )
            except Exception:
                generation = None

            try:
                raw = await _call_rewriter(self.settings, model, system_prompt, user_prompt)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[rewriter] HTTP %s: %s",
                    exc.response.status_code,
                    exc.response.text[:300],
                )
                _end_gen(generation, output=None, level="ERROR",
                         status_message=f"HTTP {exc.response.status_code}")
                break
            except httpx.HTTPError as exc:
                logger.warning("[rewriter] network error: %s", exc)
                _end_gen(generation, output=None, level="ERROR",
                         status_message=exc.__class__.__name__)
                break

            try:
                content = raw["choices"][0]["message"]["content"]
                parsed = _parse_content(content)
            except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("[rewriter] unparsable: %s", exc)
                _end_gen(generation, output=None, level="ERROR",
                         status_message=f"unparsable: {exc.__class__.__name__}")
                break

            new_with_placeholders = parsed.get("rewritten_text") or ""
            if not new_with_placeholders.strip():
                _end_gen(generation, output=parsed, level="WARNING",
                         status_message="empty rewritten_text")
                break
            new_text = _restore_placeholders(new_with_placeholders, saved)

            ch = parsed.get("changes")
            if isinstance(ch, list):
                all_changes.extend(str(c) for c in ch[:6])
            preserved_note_out = parsed.get("preserved") or preserved_note_out

            usage = raw.get("usage") or {}
            iter_usage: dict[str, int] = {}
            for k in usage_total:
                v = usage.get(k)
                if isinstance(v, int):
                    usage_total[k] += v
                    iter_usage[k] = v
            _end_gen(generation, output=parsed, usage=iter_usage or None)

            audit_det = await _detect(self.orchestrator, new_text, req.mode)
            iterations.append(
                IterationDiagnostic(
                    index=i,
                    ai_probability=audit_det.result.ai_probability,
                    verdict=_verdict_from_detection(audit_det),
                    summary=(audit_det.signals.llm_judge.summary
                            if audit_det.signals and audit_det.signals.llm_judge
                            else None),
                )
            )

            current_text = new_text
            current_det = audit_det

            if audit_det.result.ai_probability <= req.options.target_ai_probability:
                break

        after_block: DetectionResultBlock = current_det.result
        target_reached = after_block.ai_probability <= req.options.target_ai_probability

        # Finalise the rewrite trace with before/after metrics. The Langfuse UI
        # surfaces this on the trace card so we can scan effectiveness across
        # sessions without opening each one.
        with contextlib.suppress(Exception):
            trace.update(
                output={
                    "target_reached": target_reached,
                    "iterations": len(iterations) - 1,
                    "ai_probability_before": before_block.ai_probability,
                    "ai_probability_after": after_block.ai_probability,
                    "verdict_before": before_block.verdict,
                    "verdict_after": after_block.verdict,
                },
                metadata={
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "total_tokens": usage_total.get("total_tokens", 0),
                },
            )

        return RewriteResponse(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            rewritten_text=current_text,
            changes=all_changes,
            preserved_note=preserved_note_out,
            before=before_block,
            after=after_block,
            iterations=iterations,
            target_reached=target_reached,
            voice=req.options.voice,
            model=model,
            duration_ms=int((time.perf_counter() - started) * 1000),
            usage=RewriteUsage(**usage_total),
            severity=after_block.severity,
        )
