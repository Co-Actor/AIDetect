from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

INTERNAL_TOKEN = "test-token-12345"
JWT_SECRET = "test-jwt-secret-0123456789-abcdefghij"  # >=32 bytes for HS256


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("AIDETECT_INTERNAL_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("REDIS_URL", "")  # force in-memory cache
    monkeypatch.setenv("FEEDBACK_LOG_PATH", str(tmp_path / "feedback.jsonl"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "")  # Google sign-in disabled by default
    monkeypatch.setenv("APP_BASE_URL", "http://testserver")
    monkeypatch.setenv("TRIAL_CHECK_LIMIT", "3")
    monkeypatch.setenv("ADMIN_EMAILS", "i.salmova@cccrafts.ai")
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
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Hermetic in-memory SQLite shared across sessions via a StaticPool.

    A single underlying connection keeps the schema alive for the whole test, so
    independent ``AsyncSession``s (one per request) all see the same tables/rows.
    """
    from aidetect.db.migrate import run_migrations

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await run_migrations(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_sessionmaker(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)


class CapturingEmailSender:
    """Test double that records invitation sends instead of hitting the network."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_invitation(self, email: str, invite_url: str) -> None:
        self.sent.append((email, invite_url))


# Shared across the app-under-test and any test that wants to assert on sends.
_EMAIL_SENDER = CapturingEmailSender()


@pytest.fixture
def email_sender() -> CapturingEmailSender:
    """The capturing email sender wired into the `client` app; reset per test."""
    _EMAIL_SENDER.sent.clear()
    return _EMAIL_SENDER


@pytest_asyncio.fixture
async def client(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    from aidetect.config import get_settings
    from aidetect.db.session import get_db_session
    from aidetect.main import create_app
    from aidetect.services.email import get_email_sender

    app = create_app()

    async def _override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as session:
            yield session

    _EMAIL_SENDER.sent.clear()

    app.dependency_overrides[get_db_session] = _override_get_db_session
    app.dependency_overrides[get_settings] = get_settings  # fixed env-driven settings
    app.dependency_overrides[get_email_sender] = lambda: _EMAIL_SENDER  # no network in tests

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def invite_and_register(
    client: AsyncClient,
    email: str = "user@example.com",
    password: str = "password123",
    name: str | None = "Test User",
) -> str:
    """Seed an admin invitation for `email`, then register through it.

    Registration is invite-only by default, so tests that need a fresh user go
    through this two-step flow. Returns the new user's bearer token.
    """
    inv = await client.post(
        "/v1/admin/invitations",
        json={"email": email},
        headers={"X-API-Key": INTERNAL_TOKEN},
    )
    assert inv.status_code == 201, inv.text
    token = inv.json()["token"]
    resp = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": password, "name": name, "invite_token": token},
    )
    assert resp.status_code == 201, resp.text
    auth_token: str = resp.json()["token"]
    return auth_token


async def _register(client: AsyncClient, email: str = "user@example.com") -> str:
    return await invite_and_register(client, email)


@pytest_asyncio.fixture
async def authed_client(client: AsyncClient) -> AsyncClient:
    """Register a fresh user and return the client with its Bearer token set."""
    token = await _register(client)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Bearer header for a freshly-registered user (drop-in for protected routes)."""
    token = await _register(client)
    return {"Authorization": f"Bearer {token}"}
