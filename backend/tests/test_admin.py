from __future__ import annotations

import pytest
from httpx import AsyncClient

from .conftest import INTERNAL_TOKEN, invite_and_register

ADMIN_HEADERS = {"X-API-Key": INTERNAL_TOKEN}
# In the test env ADMIN_EMAILS is pinned to this address (see conftest._env).
ADMIN_EMAIL = "i.salmova@cccrafts.ai"


@pytest.mark.asyncio
async def test_admin_users_via_internal_token(client: AsyncClient) -> None:
    await invite_and_register(client, "someone@example.com")
    resp = await client.get("/v1/admin/users", headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert "someone@example.com" in [u["email"] for u in rows]
    assert all({"id", "email", "is_admin", "created_at"} <= u.keys() for u in rows)


@pytest.mark.asyncio
async def test_configured_email_becomes_admin(client: AsyncClient) -> None:
    token = await invite_and_register(client, ADMIN_EMAIL)
    me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["is_admin"] is True


@pytest.mark.asyncio
async def test_admin_user_jwt_can_list_users(client: AsyncClient) -> None:
    token = await invite_and_register(client, ADMIN_EMAIL)
    resp = await client.get("/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    admin_row = next(u for u in resp.json() if u["email"] == ADMIN_EMAIL)
    assert admin_row["is_admin"] is True


@pytest.mark.asyncio
async def test_admin_user_jwt_can_invite(client: AsyncClient) -> None:
    token = await invite_and_register(client, ADMIN_EMAIL)
    resp = await client.post(
        "/v1/admin/invitations",
        json={"email": "invited-by-admin@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "invited-by-admin@example.com"


@pytest.mark.asyncio
async def test_normal_user_is_not_admin(client: AsyncClient) -> None:
    token = await invite_and_register(client, "regular@example.com")
    me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["is_admin"] is False


@pytest.mark.asyncio
async def test_normal_user_jwt_forbidden_on_admin(client: AsyncClient) -> None:
    token = await invite_and_register(client, "regular@example.com")
    hdrs = {"Authorization": f"Bearer {token}"}
    users = await client.get("/v1/admin/users", headers=hdrs)
    assert users.status_code == 403
    invite = await client.post(
        "/v1/admin/invitations", json={"email": "x@example.com"}, headers=hdrs
    )
    assert invite.status_code == 403


@pytest.mark.asyncio
async def test_admin_users_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/v1/admin/users")
    assert resp.status_code == 401


async def _register_with_id(client: AsyncClient, email: str) -> tuple[str, str]:
    """Register a user via invite; return (bearer_token, user_id)."""
    token = await invite_and_register(client, email)
    me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["id"]


@pytest.mark.asyncio
async def test_admin_can_promote_and_demote_user(client: AsyncClient) -> None:
    admin_token = await invite_and_register(client, ADMIN_EMAIL)
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}
    user_token, user_id = await _register_with_id(client, "promote-me@example.com")
    user_hdrs = {"Authorization": f"Bearer {user_token}"}

    r = await client.patch(
        f"/v1/admin/users/{user_id}", json={"is_admin": True}, headers=admin_hdrs
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_admin"] is True
    # The promoted user's existing token now authorizes admin routes (role is
    # resolved per-request, no re-login needed).
    assert (await client.get("/v1/admin/users", headers=user_hdrs)).status_code == 200
    assert (await client.get("/v1/auth/me", headers=user_hdrs)).json()["is_admin"] is True

    r = await client.patch(
        f"/v1/admin/users/{user_id}", json={"is_admin": False}, headers=admin_hdrs
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_admin"] is False
    assert (await client.get("/v1/admin/users", headers=user_hdrs)).status_code == 403


@pytest.mark.asyncio
async def test_internal_token_can_promote(client: AsyncClient) -> None:
    _, user_id = await _register_with_id(client, "promote2@example.com")
    r = await client.patch(
        f"/v1/admin/users/{user_id}", json={"is_admin": True}, headers=ADMIN_HEADERS
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_admin"] is True


@pytest.mark.asyncio
async def test_cannot_demote_configured_admin(client: AsyncClient) -> None:
    _, admin_id = await _register_with_id(client, ADMIN_EMAIL)
    # Even the internal token can't demote a user pinned by ADMIN_EMAILS.
    r = await client.patch(
        f"/v1/admin/users/{admin_id}", json={"is_admin": False}, headers=ADMIN_HEADERS
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_cannot_change_own_role(client: AsyncClient) -> None:
    admin_token, admin_id = await _register_with_id(client, ADMIN_EMAIL)
    r = await client.patch(
        f"/v1/admin/users/{admin_id}",
        json={"is_admin": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_admin_can_delete_user(client: AsyncClient) -> None:
    admin_token = await invite_and_register(client, ADMIN_EMAIL)
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}
    _, user_id = await _register_with_id(client, "delete-me@example.com")

    r = await client.delete(f"/v1/admin/users/{user_id}", headers=admin_hdrs)
    assert r.status_code == 204, r.text
    listed = await client.get("/v1/admin/users", headers=admin_hdrs)
    assert "delete-me@example.com" not in [u["email"] for u in listed.json()]


@pytest.mark.asyncio
async def test_cannot_delete_self(client: AsyncClient) -> None:
    admin_token, admin_id = await _register_with_id(client, ADMIN_EMAIL)
    r = await client.delete(
        f"/v1/admin/users/{admin_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_cannot_delete_service_account(client: AsyncClient, db_sessionmaker) -> None:
    from aidetect.db.models import User

    async with db_sessionmaker() as session:
        svc = User(email="service@aidetect.local", name="Service (API)")
        session.add(svc)
        await session.commit()
        await session.refresh(svc)
        svc_id = str(svc.id)

    r = await client.delete(f"/v1/admin/users/{svc_id}", headers=ADMIN_HEADERS)
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_delete_missing_user_404(client: AsyncClient) -> None:
    r = await client.delete(
        "/v1/admin/users/00000000-0000-0000-0000-000000000000", headers=ADMIN_HEADERS
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_users(client: AsyncClient) -> None:
    user_token = await invite_and_register(client, "regular@example.com")
    user_hdrs = {"Authorization": f"Bearer {user_token}"}
    _, target_id = await _register_with_id(client, "target@example.com")

    patch = await client.patch(
        f"/v1/admin/users/{target_id}", json={"is_admin": True}, headers=user_hdrs
    )
    assert patch.status_code == 403
    delete = await client.delete(f"/v1/admin/users/{target_id}", headers=user_hdrs)
    assert delete.status_code == 403
