from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_healthz(client) -> None:
    resp = await client.get("/v1/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz(client) -> None:
    resp = await client.get("/v1/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "rubric_version" in body
