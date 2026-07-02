from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from aidetect.config import Settings
from aidetect.services import google_oauth
from aidetect.services.google_oauth import GoogleIdentity

from .conftest import INTERNAL_TOKEN


async def _invite(client, email: str) -> str:
    """Seed a pending admin invitation and return its token."""
    resp = await client.post(
        "/v1/admin/invitations",
        json={"email": email},
        headers={"X-API-Key": INTERNAL_TOKEN},
    )
    assert resp.status_code == 201, resp.text
    token: str = resp.json()["token"]
    return token


@pytest.mark.asyncio
async def test_register_success(client) -> None:
    token = await _invite(client, "alice@example.com")
    resp = await client.post(
        "/v1/auth/register",
        json={
            "email": "alice@example.com",
            "password": "supersecret",
            "name": "Alice",
            "invite_token": token,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"]
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["name"] == "Alice"
    assert "id" in body["user"]


@pytest.mark.asyncio
async def test_register_duplicate_email_conflict(client, db_sessionmaker) -> None:
    token = await _invite(client, "dup@example.com")
    first = await client.post(
        "/v1/auth/register",
        json={"email": "dup@example.com", "password": "supersecret", "invite_token": token},
    )
    assert first.status_code == 201

    # A second *valid* invite for the same (now-registered) email still hits the
    # duplicate-email guard rather than creating a second account.
    from aidetect.db.models import Invitation

    async with db_sessionmaker() as session:
        inv = Invitation(email="dup@example.com", token="dup-second-token", status="pending")
        session.add(inv)
        await session.commit()

    second = await client.post(
        "/v1/auth/register",
        json={
            "email": "dup@example.com",
            "password": "supersecret",
            "invite_token": "dup-second-token",
        },
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_register_duplicate_race_returns_conflict(client, monkeypatch) -> None:
    # Seed a real invite first (monkeypatches below don't touch the token lookup).
    token = await _invite(client, "race@example.com")

    from aidetect.api.v1 import auth as auth_router

    async def no_existing_user(session, email):
        return None

    async def duplicate_insert(session, **kwargs):
        raise IntegrityError("insert users", {}, Exception("duplicate key"))

    monkeypatch.setattr(auth_router.repository, "get_user_by_email", no_existing_user)
    monkeypatch.setattr(auth_router.repository, "create_user", duplicate_insert)

    resp = await client.post(
        "/v1/auth/register",
        json={"email": "race@example.com", "password": "supersecret", "invite_token": token},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "email already registered"


@pytest.mark.asyncio
async def test_register_email_normalized(client) -> None:
    token = await _invite(client, "  MixedCase@Example.com ")
    resp = await client.post(
        "/v1/auth/register",
        json={
            "email": "  MixedCase@Example.com ",
            "password": "supersecret",
            "invite_token": token,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["user"]["email"] == "mixedcase@example.com"
    # A login with the original (uncased) email must hit the same row.
    login = await client.post(
        "/v1/auth/login",
        json={"email": "mixedcase@example.com", "password": "supersecret"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_login_success(client) -> None:
    invite = await _invite(client, "bob@example.com")
    await client.post(
        "/v1/auth/register",
        json={"email": "bob@example.com", "password": "supersecret", "invite_token": invite},
    )
    resp = await client.post(
        "/v1/auth/login",
        json={"email": "bob@example.com", "password": "supersecret"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["token"]


@pytest.mark.asyncio
async def test_login_wrong_password(client) -> None:
    invite = await _invite(client, "carol@example.com")
    await client.post(
        "/v1/auth/register",
        json={"email": "carol@example.com", "password": "supersecret", "invite_token": invite},
    )
    resp = await client.post(
        "/v1/auth/login",
        json={"email": "carol@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_long_password_does_not_500(client) -> None:
    # bcrypt rejects inputs over 72 bytes; a long password-manager password must
    # still register (truncated to 72 bytes) instead of crashing with a 500.
    long_pw = "a" * 100  # 100 bytes — well past bcrypt's 72-byte limit
    invite = await _invite(client, "longpw@example.com")
    reg = await client.post(
        "/v1/auth/register",
        json={"email": "longpw@example.com", "password": long_pw, "invite_token": invite},
    )
    assert reg.status_code == 201, reg.text
    # Hashing and verification truncate identically, so login still succeeds.
    login = await client.post(
        "/v1/auth/login",
        json={"email": "longpw@example.com", "password": long_pw},
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_me_with_token(client) -> None:
    invite = await _invite(client, "dave@example.com")
    reg = await client.post(
        "/v1/auth/register",
        json={
            "email": "dave@example.com",
            "password": "supersecret",
            "name": "Dave",
            "invite_token": invite,
        },
    )
    token = reg.json()["token"]
    resp = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "dave@example.com"
    assert resp.json()["name"] == "Dave"


@pytest.mark.asyncio
async def test_me_without_token(client) -> None:
    resp = await client.get("/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_google_disabled_returns_400(client) -> None:
    # GOOGLE_OAUTH_CLIENT_ID is unset in the test env → sign-in unavailable.
    resp = await client.post("/v1/auth/google", json={"id_token": "whatever"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_google_rejects_unverified_email_claim(monkeypatch) -> None:
    def fake_verify_sync(id_token_str: str, client_id: str) -> dict[str, object]:
        return {
            "sub": "google-sub-123",
            "email": "victim@example.com",
            "email_verified": False,
            "name": "Unverified User",
        }

    monkeypatch.setattr(google_oauth, "_verify_sync", fake_verify_sync)
    settings = Settings(google_oauth_client_id="google-client-id")

    with pytest.raises(HTTPException) as exc:
        await google_oauth.verify_google_id_token("fake-token", settings)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_google_success_upserts_user(client, monkeypatch) -> None:
    async def fake_verify(id_token_str: str, settings) -> GoogleIdentity:
        return GoogleIdentity(sub="google-sub-123", email="gmail@example.com", name="G User")

    monkeypatch.setattr(google_oauth, "verify_google_id_token", fake_verify)
    # The router imports the symbol directly, so patch it there too.
    from aidetect.api.v1 import auth as auth_router

    monkeypatch.setattr(auth_router, "verify_google_id_token", fake_verify)

    # New-account Google sign-in is invite-gated; seed a pending invitation.
    await _invite(client, "gmail@example.com")

    resp = await client.post("/v1/auth/google", json={"id_token": "fake-token"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"]
    assert body["user"]["email"] == "gmail@example.com"

    # Token authenticates against the freshly-upserted user.
    me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "gmail@example.com"
