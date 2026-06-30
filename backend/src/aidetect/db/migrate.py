"""Lightweight, Alembic-free migration runner.

SQLite (tests): build the schema straight from the ORM metadata.
Postgres (prod): apply the raw ``backend/migrations/*.up.sql`` files in
filename order, recording each in a ``schema_migrations`` bookkeeping table so
re-runs are idempotent.

The migrations directory is resolved from ``AIDETECT_MIGRATIONS_DIR``, the
runtime working directory (``/app`` in Docker), or the local source tree so it
works from ``make migrate``, ``python -m aidetect.db.migrate`` and the app
lifespan after package installation.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from aidetect.db.models import Base


def _candidate_migration_dirs() -> list[Path]:
    env_dir = os.getenv("AIDETECT_MIGRATIONS_DIR")
    candidates = [
        Path(env_dir).expanduser() if env_dir else None,
        Path.cwd() / "migrations",
        Path("/app/migrations"),
        # Local source tree: .../backend/src/aidetect/db/migrate.py -> .../backend
        Path(__file__).resolve().parents[3] / "migrations",
    ]

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _resolve_migrations_dir() -> Path | None:
    for candidate in _candidate_migration_dirs():
        if candidate.is_dir() and any(candidate.glob("*.up.sql")):
            return candidate
    return None


def _migration_files() -> list[Path]:
    migrations_dir = _resolve_migrations_dir()
    if migrations_dir is None:
        return []
    return sorted(migrations_dir.glob("*.up.sql"))


def _version_of(path: Path) -> str:
    # "001_auth_and_sharing.up.sql" -> "001_auth_and_sharing"
    return path.name[: -len(".up.sql")]


async def _exec_sql_script(conn: AsyncConnection, sql: str) -> None:
    """Execute a multi-statement SQL script on Postgres/asyncpg.

    asyncpg routes ``exec_driver_sql`` through the extended (prepared-statement)
    protocol, which rejects scripts containing more than one command
    ("cannot insert multiple commands into a prepared statement"). Run the script
    through the underlying asyncpg connection's simple-query protocol instead,
    which executes every statement in the script in one round-trip.
    """
    raw = await conn.get_raw_connection()
    driver_conn = raw.driver_connection
    if driver_conn is None:  # pragma: no cover - asyncpg always exposes one
        raise RuntimeError("no raw asyncpg connection available to apply migrations")
    await driver_conn.execute(sql)


async def run_migrations(engine: AsyncEngine) -> None:
    if engine.dialect.name == "sqlite":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version text PRIMARY KEY, "
                "applied_at timestamptz NOT NULL DEFAULT now())"
            )
        )
        applied = {
            row[0] for row in (await conn.execute(text("SELECT version FROM schema_migrations")))
        }
        migration_files = _migration_files()
        if not migration_files:
            searched = ", ".join(str(p) for p in _candidate_migration_dirs())
            raise RuntimeError(f"no Postgres migration files found; searched: {searched}")

        for path in migration_files:
            version = _version_of(path)
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            await _exec_sql_script(conn, sql)
            await conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": version},
            )


async def _main() -> None:
    from aidetect.db.session import get_engine

    engine = get_engine()
    try:
        await run_migrations(engine)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
