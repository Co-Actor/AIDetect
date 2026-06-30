from __future__ import annotations

import pytest

SAMPLE = (
    "Let's dive into this game-changer. In today's fast-paced world, we leverage "
    "innovation seamlessly. At the end of the day, it's no secret that this matters."
)


@pytest.mark.asyncio
async def test_detect_requires_token(client) -> None:
    resp = await client.post("/v1/detections", json={"text": "hello"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_detect_rejects_invalid_token(client) -> None:
    resp = await client.post(
        "/v1/detections",
        headers={"Authorization": "Bearer not-a-real-jwt"},
        json={"text": "hello"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_detect_smoke_with_patterns(client, auth_headers) -> None:
    resp = await client.post(
        "/v1/detections",
        headers=auth_headers,
        json={"text": SAMPLE, "mode": "fast"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["object"] == "detection"
    assert 0.0 <= body["result"]["ai_probability"] <= 1.0
    assert body["result"]["verdict"] in {
        "human",
        "likely_human",
        "uncertain",
        "likely_ai",
        "ai",
    }
    assert body["signals"]["patterns"]["matches"], "expected at least one pattern hit"
    assert body["request"]["text_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_detect_allows_internal_token_for_calibration(client) -> None:
    resp = await client.post(
        "/v1/detections",
        headers={"X-API-Key": "test-token-12345"},
        json={"text": SAMPLE, "mode": "fast"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["object"] == "detection"


@pytest.mark.asyncio
async def test_detect_allows_internal_bearer_token(client) -> None:
    resp = await client.post(
        "/v1/detections",
        headers={"Authorization": "Bearer test-token-12345"},
        json={"text": SAMPLE, "mode": "fast"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["object"] == "detection"


@pytest.mark.asyncio
async def test_detect_uses_result_cache(client, auth_headers) -> None:
    headers = {**auth_headers}
    first = await client.post(
        "/v1/detections", headers=headers, json={"text": SAMPLE, "mode": "fast"}
    )
    second = await client.post(
        "/v1/detections", headers=headers, json={"text": SAMPLE, "mode": "fast"}
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["metadata"]["cached"] is False
    assert second.json()["metadata"]["cached"] is True
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_detect_idempotency_key(client, auth_headers) -> None:
    headers = {**auth_headers, "Idempotency-Key": "abc-123"}
    a = await client.post("/v1/detections", headers=headers, json={"text": "different text body"})
    b = await client.post("/v1/detections", headers=headers, json={"text": "different text body"})
    assert a.json()["id"] == b.json()["id"]
    assert b.json()["metadata"]["cached"] is True


@pytest.mark.asyncio
async def test_detect_text_too_large(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setenv("MAX_TEXT_LENGTH", "10")
    from aidetect import config as cfg

    cfg.get_settings.cache_clear()
    resp = await client.post(
        "/v1/detections",
        headers=auth_headers,
        json={"text": "x" * 100, "mode": "fast"},
    )
    assert resp.status_code == 413
