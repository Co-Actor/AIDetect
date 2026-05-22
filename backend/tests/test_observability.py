"""Smoke tests for the Langfuse observability wrapper.

We do not exercise the actual Langfuse cloud here — only verify that:
  * `get_observer()` returns a `NoopObserver` when keys are missing or
    the feature flag is off, even if Langfuse is installed.
  * The Noop observer's surface is safe to call from the orchestrator and
    rewriter without raising — chained calls (`trace.generation(...).end(...)`)
    must keep working so production-style call sites stay clean.
  * Cache stays clean when tracing is disabled — no `t:<detection_id>` keys.
"""
from __future__ import annotations

import pytest

from aidetect.services.observability import NoopObserver, get_observer
from aidetect.services.observability.langfuse_client import (
    _NoopTrace,
    reset_observer,
)


@pytest.fixture(autouse=True)
def _reset_observer() -> None:
    """Drop the singleton between cases so each test sees fresh env."""
    reset_observer()
    yield
    reset_observer()


def test_get_observer_returns_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from aidetect import config as cfg

    cfg.get_settings.cache_clear()
    obs = get_observer()
    assert isinstance(obs, NoopObserver)
    assert obs.enabled is False


def test_get_observer_returns_noop_when_keys_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if the flag is on, missing credentials must downgrade to noop."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from aidetect import config as cfg

    cfg.get_settings.cache_clear()
    obs = get_observer()
    assert isinstance(obs, NoopObserver)


def test_noop_trace_chained_calls_are_safe() -> None:
    """The orchestrator/rewriter call `trace.generation(...).end(...)` and
    `trace.update(...)` unconditionally — those must work on the noop trace."""
    obs = NoopObserver()
    trace = obs.start_detection_trace(
        text_hash="abc", mode="fast", language="en",
        rubric_version="v1", model_version="aidetect-0.1.0",
    )
    assert isinstance(trace, _NoopTrace)
    # Chained calls — must not raise.
    gen = trace.generation(name="x", model="y", input={})
    gen.end(output={"ok": True}, usage_details={"input": 10, "output": 5})
    trace.update(output={"final": True})
    # No-op id sentinel so the orchestrator skips storing a useless mapping.
    assert trace.id == "noop"
    assert gen.id == "noop"


def test_noop_score_detection_is_safe() -> None:
    """The /v1/feedback path calls `observer.score_detection(...)` whenever a
    trace_id is found in cache; with the noop observer this should be a no-op
    that returns None instead of raising."""
    obs = NoopObserver()
    assert obs.score_detection(trace_id="any", name="user_feedback", value=1.0) is None
    assert obs.flush() is None


@pytest.mark.asyncio
async def test_detection_does_not_cache_trace_id_when_disabled(
    client, auth_headers, monkeypatch
) -> None:
    """When Langfuse is off the orchestrator must not write a `t:<id>` entry —
    the noop trace's id is the sentinel 'noop' and the orchestrator skips it."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    from aidetect import config as cfg

    cfg.get_settings.cache_clear()
    reset_observer()

    resp = await client.post(
        "/v1/detections",
        headers=auth_headers,
        json={"text": "Some sample text to detect.", "mode": "fast"},
    )
    assert resp.status_code == 201
    detection_id = resp.json()["id"]

    from aidetect.services.cache import get_cache

    cache = await get_cache(cfg.get_settings())
    assert await cache.get(f"t:{detection_id}") is None
