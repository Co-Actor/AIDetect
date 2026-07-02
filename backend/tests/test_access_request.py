from __future__ import annotations

import pytest

from .conftest import INTERNAL_TOKEN, invite_and_register

ADMIN_HEADERS = {"X-API-Key": INTERNAL_TOKEN}


@pytest.mark.asyncio
async def test_access_request_flow(client, email_sender) -> None:
    resp = await client.post("/v1/access-requests", json={"email": "waiting@example.com"})
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"status": "received"}

    listed = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["email"] == "waiting@example.com"
    assert rows[0]["status"] == "pending"
    request_id = rows[0]["id"]

    # Admin turns the request into an invitation.
    invited = await client.post(
        f"/v1/admin/access-requests/{request_id}/invite", headers=ADMIN_HEADERS
    )
    assert invited.status_code == 201, invited.text
    body = invited.json()
    assert body["email"] == "waiting@example.com"
    assert body["url"].endswith(f"/register?invite={body['token']}")
    assert email_sender.sent[-1] == ("waiting@example.com", body["url"])

    # The request is now marked invited.
    listed2 = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    assert listed2.json()[0]["status"] == "invited"


@pytest.mark.asyncio
async def test_access_request_is_idempotent(client) -> None:
    for _ in range(2):
        resp = await client.post("/v1/access-requests", json={"email": "dup@example.com"})
        assert resp.status_code == 201
        assert resp.json() == {"status": "received"}

    listed = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_access_request_is_idempotent_after_invite(client) -> None:
    resp = await client.post("/v1/access-requests", json={"email": "invited@example.com"})
    assert resp.status_code == 201

    listed = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    request_id = listed.json()[0]["id"]

    invited = await client.post(
        f"/v1/admin/access-requests/{request_id}/invite",
        headers=ADMIN_HEADERS,
    )
    assert invited.status_code == 201

    repeat = await client.post("/v1/access-requests", json={"email": "invited@example.com"})
    assert repeat.status_code == 201
    assert repeat.json() == {"status": "received"}

    listed2 = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    rows = listed2.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "invited"


@pytest.mark.asyncio
async def test_access_request_hides_existing_user(client) -> None:
    await invite_and_register(client, "known@example.com")

    resp = await client.post("/v1/access-requests", json={"email": "known@example.com"})
    assert resp.status_code == 201
    assert resp.json() == {"status": "received"}

    # No access request was created for an already-registered email.
    listed = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_invite_access_request_rejects_existing_user(client, email_sender) -> None:
    resp = await client.post("/v1/access-requests", json={"email": "stale@example.com"})
    assert resp.status_code == 201

    listed = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    request_id = listed.json()[0]["id"]

    await invite_and_register(client, "stale@example.com")
    email_sender.sent.clear()

    invited = await client.post(
        f"/v1/admin/access-requests/{request_id}/invite",
        headers=ADMIN_HEADERS,
    )
    assert invited.status_code == 409
    assert invited.json()["detail"] == "user already exists"
    assert email_sender.sent == []

    listed2 = await client.get("/v1/admin/access-requests", headers=ADMIN_HEADERS)
    assert listed2.json()[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_invite_missing_access_request_404(client) -> None:
    resp = await client.post(
        "/v1/admin/access-requests/00000000-0000-0000-0000-000000000000/invite",
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 404
