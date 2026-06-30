"""Service API: POST /v1/share/detect-link (internal-token auth)."""

from __future__ import annotations

from httpx import AsyncClient

# Matches AIDETECT_INTERNAL_TOKEN set by the autouse env fixture in conftest.py.
INTERNAL_TOKEN = "test-token-12345"
API_KEY = {"X-API-Key": INTERNAL_TOKEN}

SAMPLE = "This is a sample paragraph of text submitted by an employee for analysis."


async def test_detect_link_runs_detection_and_returns_public_link(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/share/detect-link",
        headers=API_KEY,
        json={"text": SAMPLE, "mode": "fast"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["token"]
    assert body["url"].endswith(f"/r/{body['token']}")
    assert body["trial_limit"] == 3
    # Full DetectionResponse is returned inline so no second call is needed.
    assert "id" in body["result"]
    assert "verdict" in body["result"]["result"]

    # The link is publicly viewable without any auth.
    pub = await client.get(f"/v1/share/{body['token']}")
    assert pub.status_code == 200
    pub_body = pub.json()
    assert pub_body["active"] is True
    assert pub_body["result"]["id"] == body["result"]["id"]
    assert pub_body["input_text"] == SAMPLE


async def test_detect_link_mode_defaults_to_balanced(client: AsyncClient) -> None:
    # mode omitted → balanced, independent of the server DEFAULT_MODE.
    resp = await client.post("/v1/share/detect-link", headers=API_KEY, json={"text": SAMPLE})
    assert resp.status_code == 201, resp.text
    assert resp.json()["result"]["metadata"]["mode"] == "balanced"


async def test_detect_link_rejects_unknown_mode(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/share/detect-link", headers=API_KEY, json={"text": SAMPLE, "mode": "turbo"}
    )
    assert resp.status_code == 422


async def test_detect_link_quota_applies_to_link(client: AsyncClient) -> None:
    token = (
        await client.post("/v1/share/detect-link", headers=API_KEY, json={"text": SAMPLE})
    ).json()["token"]

    for _ in range(3):
        r = await client.post(f"/v1/share/{token}/trial", json={"text": "a quick trial check"})
        assert r.status_code == 201, r.text
    blocked = await client.post(f"/v1/share/{token}/trial", json={"text": "one too many"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "You've used all 3 free checks. Sign up to keep using AIDetect."


async def test_detect_link_requires_internal_token(client: AsyncClient) -> None:
    no_token = await client.post("/v1/share/detect-link", json={"text": SAMPLE})
    assert no_token.status_code == 401

    wrong = await client.post(
        "/v1/share/detect-link",
        headers={"X-API-Key": "not-the-token"},
        json={"text": SAMPLE},
    )
    assert wrong.status_code == 403
