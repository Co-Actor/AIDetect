"""Langfuse client wrapper with a graceful no-op fallback.

The detector and rewriter call `get_observer()` and use the returned object
unconditionally. When the user did not configure Langfuse (no public/secret
key, or `LANGFUSE_ENABLED=0`) we return a `NoopObserver` instance whose every
method is a cheap no-op, so the call sites stay clean.

Design goals:
  * Zero impact on hot path: client init is lazy and singleton.
  * Network failures never leak: we wrap calls in try/except and log.
  * No coupling to FastAPI request lifecycle — observability is just a side
    channel. Each trace is fully described by a `text_hash` so we can
    correlate it with cached results, ground-truth and Co.Actor evaluations.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from aidetect.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ── Protocol types ──────────────────────────────────────────────────


class _TraceLike(Protocol):
    """Subset of Langfuse Trace methods we rely on."""

    def update(self, **kwargs: Any) -> Any: ...
    def generation(self, **kwargs: Any) -> Any: ...
    def span(self, **kwargs: Any) -> Any: ...
    def score(self, **kwargs: Any) -> Any: ...


# ── No-op (always works) ────────────────────────────────────────────


class _NoopTrace:
    """Drop-in stand-in for a Langfuse trace when tracing is disabled."""

    id: str = "noop"

    def update(self, **_kwargs: Any) -> _NoopTrace:
        return self

    def generation(self, **_kwargs: Any) -> _NoopGeneration:
        return _NoopGeneration()

    def span(self, **_kwargs: Any) -> _NoopSpan:
        return _NoopSpan()

    def score(self, **_kwargs: Any) -> None:
        return None


class _NoopGeneration:
    id: str = "noop"

    def update(self, **_kwargs: Any) -> _NoopGeneration:
        return self

    def end(self, **_kwargs: Any) -> _NoopGeneration:
        return self


class _NoopSpan:
    id: str = "noop"

    def update(self, **_kwargs: Any) -> _NoopSpan:
        return self

    def end(self, **_kwargs: Any) -> _NoopSpan:
        return self


class NoopObserver:
    """Public observer that records nothing.

    Returned by `get_observer()` whenever Langfuse is disabled or unreachable.
    Mirrors the surface of `LangfuseObserver` so call sites are identical.
    """

    enabled: bool = False

    def start_detection_trace(
        self,
        *,
        text_hash: str,
        mode: str,
        language: str | None,
        rubric_version: str,
        model_version: str,
        api_key_label: str | None = None,
        cached: bool = False,
    ) -> _TraceLike:
        return _NoopTrace()  # type: ignore[return-value]

    def start_rewrite_trace(
        self,
        *,
        text_hash: str,
        mode: str,
        voice: str | None,
        target_ai: float,
        max_iterations: int,
        api_key_label: str | None = None,
    ) -> _TraceLike:
        return _NoopTrace()  # type: ignore[return-value]

    def score_detection(
        self,
        *,
        trace_id: str | None,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None


# ── Real Langfuse-backed observer ───────────────────────────────────


class LangfuseObserver:
    """Thin wrapper around the Langfuse SDK.

    We call `client.trace(...)` and let callers attach generations / spans
    directly. The wrapper exists so we can hide the SDK behind a stable
    interface and swap it out (or no-op out) without touching call sites.
    """

    enabled: bool = True

    def __init__(self, settings: Settings) -> None:
        # Imported lazily so the dependency stays optional.
        from langfuse import Langfuse  # type: ignore[import-not-found]

        self._client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            release=settings.langfuse_release or settings.model_version,
            environment=settings.langfuse_environment or settings.environment,
        )
        logger.info(
            "[langfuse] enabled (host=%s, env=%s, release=%s)",
            settings.langfuse_host,
            settings.langfuse_environment or settings.environment,
            settings.langfuse_release or settings.model_version,
        )

    def start_detection_trace(
        self,
        *,
        text_hash: str,
        mode: str,
        language: str | None,
        rubric_version: str,
        model_version: str,
        api_key_label: str | None = None,
        cached: bool = False,
    ) -> _TraceLike:
        try:
            return self._client.trace(  # type: ignore[no-any-return]
                name="detection",
                tags=["detection", f"mode:{mode}"],
                metadata={
                    "text_hash": text_hash,
                    "mode": mode,
                    "language": language,
                    "rubric_version": rubric_version,
                    "model_version": model_version,
                    "api_key_label": api_key_label,
                    "cached": cached,
                },
            )
        except Exception as exc:
            logger.warning("[langfuse] failed to start detection trace: %s", exc)
            return _NoopTrace()  # type: ignore[return-value]

    def start_rewrite_trace(
        self,
        *,
        text_hash: str,
        mode: str,
        voice: str | None,
        target_ai: float,
        max_iterations: int,
        api_key_label: str | None = None,
    ) -> _TraceLike:
        try:
            return self._client.trace(  # type: ignore[no-any-return]
                name="rewrite",
                tags=["rewrite", f"mode:{mode}", f"voice:{voice or 'auto'}"],
                metadata={
                    "text_hash": text_hash,
                    "mode": mode,
                    "voice": voice,
                    "target_ai_probability": target_ai,
                    "max_iterations": max_iterations,
                    "api_key_label": api_key_label,
                },
            )
        except Exception as exc:
            logger.warning("[langfuse] failed to start rewrite trace: %s", exc)
            return _NoopTrace()  # type: ignore[return-value]

    def score_detection(
        self,
        *,
        trace_id: str | None,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        if trace_id is None:
            return
        try:
            self._client.score(
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment,
            )
        except Exception as exc:
            logger.warning("[langfuse] failed to record score: %s", exc)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("[langfuse] flush failed: %s", exc)


# ── Singleton ───────────────────────────────────────────────────────


_observer: LangfuseObserver | NoopObserver | None = None


def get_observer() -> LangfuseObserver | NoopObserver:
    """Return the singleton observer. Lazy-inits on first call."""
    global _observer
    if _observer is not None:
        return _observer

    settings = get_settings()
    if (
        not settings.langfuse_enabled
        or not settings.langfuse_public_key
        or not settings.langfuse_secret_key
    ):
        _observer = NoopObserver()
        return _observer

    try:
        _observer = LangfuseObserver(settings)
    except Exception as exc:  # ImportError, ValueError, network during ping
        logger.warning(
            "[langfuse] failed to initialise (%s), falling back to no-op", exc
        )
        _observer = NoopObserver()
    return _observer


def reset_observer() -> None:
    """Drop the singleton — used by tests that toggle env between cases."""
    global _observer
    _observer = None


def flush_observer() -> None:
    """Flush pending events. Call on shutdown."""
    obs = get_observer()
    if isinstance(obs, LangfuseObserver):
        obs.flush()


__all__ = [
    "LangfuseObserver",
    "NoopObserver",
    "flush_observer",
    "get_observer",
    "reset_observer",
]
