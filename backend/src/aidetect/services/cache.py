"""Async cache with optional Redis backend and in-memory fallback.

Used for two purposes:
  - result cache:        key = f"r:{rubric_version}:{model_version}:{mode}:{sha256(text)}"
  - idempotency cache:   key = f"i:{idempotency_key}"

If REDIS_URL is unset or the connection fails, an in-memory dict is used. This is
fine for dev and for unit tests; production should always have Redis available.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import redis.asyncio as redis_asyncio

from aidetect.config import Settings

logger = logging.getLogger(__name__)


class _MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.time():
                self._store.pop(key, None)
                return None
            return value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        async with self._lock:
            self._store[key] = (time.time() + ttl, value)

    async def aclose(self) -> None:
        return None


class Cache:
    def __init__(self, backend: redis_asyncio.Redis | _MemoryCache, name: str) -> None:
        self._backend = backend
        self.name = name

    async def get(self, key: str) -> str | None:
        try:
            value = await self._backend.get(key)
        except Exception as exc:
            logger.warning("[cache:%s] get failed: %s", self.name, exc)
            return None
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        try:
            await self._backend.setex(key, ttl, value)
        except Exception as exc:
            logger.warning("[cache:%s] setex failed: %s", self.name, exc)

    async def aclose(self) -> None:
        await self._backend.aclose()


_cache_instance: Cache | None = None
_cache_lock = asyncio.Lock()


async def get_cache(settings: Settings) -> Cache:
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance
    async with _cache_lock:
        if _cache_instance is not None:
            return _cache_instance
        backend: Any
        if not settings.redis_url:
            logger.info("[cache] REDIS_URL not set — using in-memory cache")
            backend = _MemoryCache()
            name = "memory"
        else:
            try:
                client: redis_asyncio.Redis = redis_asyncio.from_url(
                    settings.redis_url, decode_responses=False
                )
                await client.ping()
                backend = client
                name = "redis"
                logger.info("[cache] using Redis at %s", settings.redis_url)
            except Exception as exc:
                logger.warning(
                    "[cache] Redis unreachable (%s) — falling back to in-memory", exc
                )
                backend = _MemoryCache()
                name = "memory"
        _cache_instance = Cache(backend, name)
        return _cache_instance


async def close_cache() -> None:
    global _cache_instance
    if _cache_instance is not None:
        await _cache_instance.aclose()
        _cache_instance = None
