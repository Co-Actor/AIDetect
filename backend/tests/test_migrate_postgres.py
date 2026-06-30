"""Regression test for the Postgres migration runner.

The hermetic suite runs on SQLite (the ``create_all`` path), so it never
exercises the raw-SQL Postgres path. This test applies the real
``backend/migrations/*.up.sql`` scripts against a Postgres instance when
``TEST_DATABASE_URL`` is set. It guards against the asyncpg regression
"cannot insert multiple commands into a prepared statement" (a multi-statement
``.up.sql`` must run through the simple-query protocol). Skipped when no Postgres
URL is available (e.g. CI without a database service).

Run locally with:
    TEST_DATABASE_URL=postgresql+asyncpg://aidetect:aidetect@localhost:5433/aidetect \
        uv run pytest tests/test_migrate_postgres.py
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PG_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="set TEST_DATABASE_URL to a postgresql+asyncpg DSN to run the Postgres migration test",
)


async def test_run_migrations_postgres_idempotent() -> None:
    from aidetect.db.migrate import run_migrations

    assert PG_URL is not None
    engine = create_async_engine(PG_URL)
    try:
        # First run applies the multi-statement script; the second must be a
        # no-op (version already recorded), not an error.
        await run_migrations(engine)
        await run_migrations(engine)

        async with engine.connect() as conn:
            for table in ("users", "detections", "share_links", "schema_migrations"):
                regclass = (
                    await conn.execute(
                        text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
                    )
                ).scalar()
                assert regclass is not None, f"table {table!r} was not created"

            versions = {
                row[0]
                for row in (await conn.execute(text("SELECT version FROM schema_migrations")))
            }
            assert "001_auth_and_sharing" in versions
    finally:
        await engine.dispose()
