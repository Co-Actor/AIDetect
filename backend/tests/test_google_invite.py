from __future__ import annotations

import pytest

from aidetect.services import google_oauth
from aidetect.services.google_oauth import GoogleIdentity

from .conftest import INTERNAL_TOKEN

ADMIN_HEADERS = {"X-API-Key": INTERNAL_TOKEN}


def _patch_google(monkeypatch, *, sub: str, email: str, name: str | None = None) -> None:
    async def fake_verify(id_token_str: str, settings) -> GoogleIdentity:
        return GoogleIdentity(sub=sub, email=email, name=name)

    monkeypatch.setattr(google_oauth, "verify_google_id_token", fake_verify)
    from aidetect.api.v1 import auth as auth_router

    monkeypatch.setattr(auth_router, "verify_google_id_token", fake_verify)


async def _invite(client, email: str) -> None:
    resp = await client.post(
        "/v1/admin/invitations", json={"email": email}, headers=ADMIN_HEADERS
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_google_uninvited_new_user_forbidden(client, monkeypatch) -> None:
    _patch_google(monkeypatch, sub="g-sub-1", email="stranger@example.com", name="Stranger")
    resp = await client.post("/v1/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "registration is invite-only"


@pytest.mark.asyncio
async def test_google_invited_new_user_creates_and_accepts(client, monkeypatch) -> None:
    _patch_google(monkeypatch, sub="g-sub-2", email="guest@example.com", name="Guest")
    await _invite(client, "guest@example.com")

    resp = await client.post("/v1/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == "guest@example.com"

    # The pending invitation is now accepted.
    listed = await client.get("/v1/admin/invitations", headers=ADMIN_HEADERS)
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "accepted"


@pytest.mark.asyncio
async def test_google_existing_user_signs_in(client, monkeypatch) -> None:
    # Register a normal user via invite first.
    from .conftest import invite_and_register

    await invite_and_register(client, "member@example.com")

    # Same email arrives via Google — existing-user sign-in must succeed.
    _patch_google(monkeypatch, sub="g-sub-3", email="member@example.com", name="Member")
    resp = await client.post("/v1/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == "member@example.com"


@pytest.mark.asyncio
async def test_check_invitation_endpoint(client) -> None:
    inv = await client.post(
        "/v1/admin/invitations", json={"email": "peek@example.com"}, headers=ADMIN_HEADERS
    )
    token = inv.json()["token"]

    ok = await client.get(f"/v1/auth/invitations/{token}")
    assert ok.status_code == 200
    assert ok.json() == {"email": "peek@example.com", "valid": True}

    missing = await client.get("/v1/auth/invitations/nope")
    assert missing.status_code == 200
    assert missing.json() == {"email": None, "valid": False}
