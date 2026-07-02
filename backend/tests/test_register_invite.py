from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from .conftest import INTERNAL_TOKEN

ADMIN_HEADERS = {"X-API-Key": INTERNAL_TOKEN}


async def _invite(client, email: str) -> str:
    resp = await client.post(
        "/v1/admin/invitations", json={"email": email}, headers=ADMIN_HEADERS
    )
    assert resp.status_code == 201, resp.text
    token: str = resp.json()["token"]
    return token


@pytest.mark.asyncio
async def test_register_without_invite_is_forbidden(client) -> None:
    resp = await client.post(
        "/v1/auth/register",
        json={"email": "closed@example.com", "password": "supersecret"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "registration is invite-only"


@pytest.mark.asyncio
async def test_register_with_valid_invite(client) -> None:
    token = await _invite(client, "welcome@example.com")
    resp = await client.post(
        "/v1/auth/register",
        json={
            "email": "welcome@example.com",
            "password": "supersecret",
            "invite_token": token,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["email"] == "welcome@example.com"


@pytest.mark.asyncio
async def test_invite_is_single_use(client) -> None:
    token = await _invite(client, "once@example.com")
    payload = {"email": "once@example.com", "password": "supersecret", "invite_token": token}
    first = await client.post("/v1/auth/register", json=payload)
    assert first.status_code == 201
    # The token is consumed (accepted) — a second attempt is rejected.
    second = await client.post("/v1/auth/register", json=payload)
    assert second.status_code == 403
    assert second.json()["detail"] == "invalid or expired invitation"


@pytest.mark.asyncio
async def test_invite_email_must_match(client) -> None:
    token = await _invite(client, "owner@example.com")
    resp = await client.post(
        "/v1/auth/register",
        json={"email": "someone-else@example.com", "password": "supersecret", "invite_token": token},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "invalid or expired invitation"


@pytest.mark.asyncio
async def test_expired_invite_is_rejected(client, db_sessionmaker) -> None:
    from aidetect.db.models import Invitation

    async with db_sessionmaker() as session:
        inv = Invitation(
            email="expired@example.com",
            token="expired-token-abc",
            status="pending",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add(inv)
        await session.commit()

    resp = await client.post(
        "/v1/auth/register",
        json={
            "email": "expired@example.com",
            "password": "supersecret",
            "invite_token": "expired-token-abc",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "invalid or expired invitation"
