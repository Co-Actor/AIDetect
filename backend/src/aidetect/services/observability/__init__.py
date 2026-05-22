"""Observability / tracing wrappers.

Currently exposes a Langfuse integration; the public API is designed so the
detector and rewriter can call it unconditionally — when Langfuse is not
configured every helper degrades to a cheap no-op.
"""
from aidetect.services.observability.langfuse_client import (
    LangfuseObserver,
    NoopObserver,
    flush_observer,
    get_observer,
)

__all__ = [
    "LangfuseObserver",
    "NoopObserver",
    "flush_observer",
    "get_observer",
]
