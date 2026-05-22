from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

INTERNAL_TOKEN = "test-token-12345"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("AIDETECT_INTERNAL_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("REDIS_URL", "")  # force in-memory cache
    monkeypatch.setenv("FEEDBACK_LOG_PATH", str(tmp_path / "feedback.jsonl"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Default tests should not touch OpenRouter — opt-in per-test.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    from aidetect import config as cfg

    cfg.get_settings.cache_clear()

    from aidetect.services import cache as cache_mod

    cache_mod._cache_instance = None

    from aidetect.services import aggregator as agg_mod

    agg_mod.reset_calibration_cache()
    yield
    cache_mod._cache_instance = None
    agg_mod.reset_calibration_cache()
    cfg.get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from aidetect.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": INTERNAL_TOKEN}
