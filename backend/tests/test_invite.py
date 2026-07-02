from __future__ import annotations

import pytest

from .conftest import INTERNAL_TOKEN, invite_and_register

ADMIN_HEADERS = {"X-API-Key": INTERNAL_TOKEN}


@pytest.mark.asyncio
async def test_admin_creates_invitation(client, email_sender) -> None:
    resp = await client.post(
        "/v1/admin/invitations",
        json={"email": "invitee@example.com"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "invitee@example.com"
    assert body["status"] == "pending"
    token = body["token"]
    assert body["url"].endswith(f"/register?invite={token}")

    # The email sender captured exactly this send (no network).
    assert email_sender.sent == [("invitee@example.com", body["url"])]

    listed = await client.get("/v1/admin/invitations", headers=ADMIN_HEADERS)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["email"] == "invitee@example.com"
    assert rows[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_admin_invitation_requires_token(client) -> None:
    resp = await client.post("/v1/admin/invitations", json={"email": "x@example.com"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_invitation_wrong_token(client) -> None:
    resp = await client.post(
        "/v1/admin/invitations",
        json={"email": "x@example.com"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_invitation_existing_user_conflict(client) -> None:
    await invite_and_register(client, "already@example.com")
    resp = await client.post(
        "/v1/admin/invitations",
        json={"email": "already@example.com"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "user already exists"


@pytest.mark.asyncio
async def test_admin_invitation_reuses_pending(client) -> None:
    first = await client.post(
        "/v1/admin/invitations",
        json={"email": "dup@example.com"},
        headers=ADMIN_HEADERS,
    )
    second = await client.post(
        "/v1/admin/invitations",
        json={"email": "dup@example.com"},
        headers=ADMIN_HEADERS,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    # Same pending invitation reused — no duplicate row, same token.
    assert first.json()["token"] == second.json()["token"]
    listed = await client.get("/v1/admin/invitations", headers=ADMIN_HEADERS)
    assert len(listed.json()) == 1
