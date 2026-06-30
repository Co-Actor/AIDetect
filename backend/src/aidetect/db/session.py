"""Async SQLAlchemy engine + session factory.

The engine is a lazily-built module-level singleton derived from
``settings.database_url`` so the whole app (and Alembic-free migrations) share
one connection pool. Tests override the ``get_db_session`` dependency with their
own in-memory SQLite session, so this module is never reached under pytest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aidetect.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args: dict[str, object] = {}
        # Two separate prepared-statement caches break behind transaction-pooling
        # proxies (Supabase Supavisor / PgBouncer): asyncpg's own, and SQLAlchemy's
        # asyncpg-dialect cache. Disable both; harmless on a direct/session
        # connection. Not applied to SQLite (aiosqlite ignores them anyway).
        if "+asyncpg" in url:
            connect_args["statement_cache_size"] = 0  # asyncpg's own cache
            connect_args["prepared_statement_cache_size"] = 0  # SQLAlchemy dialect cache
        _engine = create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an ``AsyncSession`` (one per request)."""
    async with get_sessionmaker()() as session:
        yield session
