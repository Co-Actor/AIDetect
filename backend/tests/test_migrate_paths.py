from __future__ import annotations


def test_migration_files_prefer_runtime_workdir(monkeypatch, tmp_path) -> None:
    from aidetect.db import migrate

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    second = migrations / "002_second.up.sql"
    first = migrations / "001_first.up.sql"
    second.write_text("SELECT 2;", encoding="utf-8")
    first.write_text("SELECT 1;", encoding="utf-8")

    monkeypatch.delenv("AIDETECT_MIGRATIONS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert migrate._migration_files() == [first, second]


def test_migration_files_allow_explicit_env_dir(monkeypatch, tmp_path) -> None:
    from aidetect.db import migrate

    env_dir = tmp_path / "env-migrations"
    env_dir.mkdir()
    migration = env_dir / "001_env.up.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")

    monkeypatch.setenv("AIDETECT_MIGRATIONS_DIR", str(env_dir))

    assert migrate._migration_files() == [migration]
