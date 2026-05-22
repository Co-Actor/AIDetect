"""Detection pipeline orchestrator.

Runs all available signal layers (in parallel for async ones), assembles the final
DetectionResponse, and serves cached / idempotent results from a Cache backend.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import uuid
from datetime import UTC, datetime

from aidetect.config import Settings
from aidetect.schemas.detection import (
    DetectionRequest,
    DetectionResponse,
    Evidence,
    EvidenceSpan,
    RequestDetails,
    ResponseMetadata,
    Signals,
)
from aidetect.services.aggregator import aggregate
from aidetect.services.cache import Cache
from aidetect.services.observability import get_observer
from aidetect.services.signals.llm_judge import compute_llm_judge
from aidetect.services.signals.patterns import compute_patterns
from aidetect.services.signals.statistical import compute_statistical


def _detect_language(text: str) -> str | None:
    try:
        from langdetect import detect  # type: ignore[import-untyped]

        return detect(text)
    except Exception:
        return None


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Orchestrator:
    def __init__(self, settings: Settings, cache: Cache) -> None:
        self.settings = settings
        self.cache = cache

    @staticmethod
    def _result_cache_key(
        rubric_version: str, model_version: str, mode: str, text_hash: str
    ) -> str:
        return f"r:{rubric_version}:{model_version}:{mode}:{text_hash}"

    @staticmethod
    def _idempotency_key(key: str) -> str:
        return f"i:{key}"

    @staticmethod
    def _trace_key(detection_id: str) -> str:
        """Cache key that maps a public detection_id → Langfuse trace_id.

        Populated by the orchestrator after a fresh detection runs, read by the
        feedback endpoint so user labels can be attached as trace scores in
        Langfuse for ground-truth accumulation.
        """
        return f"t:{detection_id}"

    async def run(
        self,
        req: DetectionRequest,
        idempotency_key: str | None,
    ) -> DetectionResponse:
        text = req.text
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rubric_version = (
            self.settings.rubric_version if req.rubric_version == "latest" else req.rubric_version
        )
        model_version = (
            self.settings.model_version if req.model_version == "latest" else req.model_version
        )

        if idempotency_key:
            cached = await self.cache.get(self._idempotency_key(idempotency_key))
            if cached:
                return self._mark_cached(DetectionResponse.model_validate_json(cached))

        result_key = self._result_cache_key(rubric_version, model_version, req.mode, text_hash)
        cached = await self.cache.get(result_key)
        if cached:
            response = self._mark_cached(DetectionResponse.model_validate_json(cached))
            if idempotency_key:
                await self.cache.setex(
                    self._idempotency_key(idempotency_key),
                    self.settings.cache_ttl_idempotency,
                    response.model_dump_json(),
                )
            return response

        lang = req.language if req.language != "auto" else (_detect_language(text) or "unknown")

        # Observability — opens a Langfuse trace for this request when the
        # provider is configured. The trace is passed down into the LLM judge
        # so every OpenRouter call is recorded as a nested generation. When
        # Langfuse is disabled the helpers return a no-op stand-in.
        observer = get_observer()
        trace = observer.start_detection_trace(
            text_hash=text_hash,
            mode=req.mode,
            language=lang,
            rubric_version=rubric_version,
            model_version=model_version,
        )

        statistical, patterns, llm_judge = await asyncio.gather(
            compute_statistical(text),
            compute_patterns(text, rubric_version=rubric_version, language=lang),
            compute_llm_judge(text, mode=req.mode, settings=self.settings, trace=trace),
        )

        result = aggregate(statistical, patterns, llm_judge, self.settings)

        signals = (
            Signals(statistical=statistical, patterns=patterns, llm_judge=llm_judge)
            if req.options.include_signals
            else None
        )

        evidence: Evidence | None = None
        if req.options.include_evidence:
            spans: list[EvidenceSpan] = []
            if patterns is not None:
                for m in patterns.matches:
                    spans.append(
                        EvidenceSpan(
                            start=m.span[0],
                            end=m.span[1],
                            type=m.category,
                            severity=m.severity,
                            reason=f"{m.category}: {m.name}",
                        )
                    )
            # Sentence-level spans: locate every flagged sentence (AI-likeness
            # >= 0.35) in the original text and emit a span so the UI can paint
            # a soft per-sentence background underneath any phrase highlights.
            if llm_judge and llm_judge.sentence_scores:
                cursor = 0
                for s in llm_judge.sentence_scores:
                    if s.score < 0.35:
                        continue
                    idx = text.find(s.text, cursor)
                    if idx < 0:
                        idx = text.find(s.text)
                        if idx < 0:
                            continue
                    end = idx + len(s.text)
                    cursor = end
                    severity: str = (
                        "high" if s.score >= 0.7
                        else "medium" if s.score >= 0.5
                        else "low"
                    )
                    spans.append(
                        EvidenceSpan(
                            start=idx,
                            end=end,
                            type="sentence_ai",
                            severity=severity,  # type: ignore[arg-type]
                            reason=s.reason or f"sentence AI-likeness {round(s.score * 100)}%",
                        )
                    )
            evidence = Evidence(spans=spans)

        rubric_scores = (
            llm_judge.rubric_scores
            if (req.options.include_rubric_scores and llm_judge and llm_judge.rubric_scores)
            else None
        )

        response = DetectionResponse(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            result=result,
            signals=signals,
            rubric_scores=rubric_scores,
            evidence=evidence,
            request=RequestDetails(
                text_hash=f"sha256:{text_hash}",
                length_chars=len(text),
                length_tokens=_approx_tokens(text),
                language_detected=lang,
            ),
            metadata=ResponseMetadata(
                model_version=model_version,
                rubric_version=rubric_version,
                mode=req.mode,
                duration_ms=0,
                cached=False,
                cost_credits=1,
            ),
        )

        payload = response.model_dump_json()
        await self.cache.setex(result_key, self.settings.cache_ttl_result, payload)
        if idempotency_key:
            await self.cache.setex(
                self._idempotency_key(idempotency_key),
                self.settings.cache_ttl_idempotency,
                payload,
            )

        # Persist detection_id → trace_id so /v1/feedback can record the user
        # label as a Langfuse score on the original trace. Only useful when
        # tracing is enabled; the noop trace has id == "noop" which we skip.
        trace_id = getattr(trace, "id", None)
        if trace_id and trace_id != "noop":
            await self.cache.setex(
                self._trace_key(str(response.id)),
                self.settings.cache_ttl_result,
                str(trace_id),
            )

        # Finalise the trace with the aggregated result so the Langfuse UI
        # shows the bottom-line ai_probability + verdict for this request.
        # Observability never fails the request — suppress any SDK error.
        with contextlib.suppress(Exception):
            trace.update(
                output={
                    "ai_probability": result.ai_probability,
                    "human_probability": result.human_probability,
                    "verdict": result.verdict,
                    "confidence": result.confidence,
                    "severity": result.severity,
                    "patterns_count": (
                        len(patterns.matches) if patterns is not None else 0
                    ),
                    "statistical_score": (
                        statistical.score if statistical is not None else None
                    ),
                    "llm_score": (llm_judge.score if llm_judge is not None else None),
                },
                metadata={"response_id": str(response.id)},
            )
        return response

    @staticmethod
    def _mark_cached(response: DetectionResponse) -> DetectionResponse:
        response.metadata.cached = True
        return response
