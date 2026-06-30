from __future__ import annotations

import pytest

EXHAUSTED = "You've used all 3 free checks. Sign up to keep using AIDetect."

_SAMPLE = (
    "Let's dive into this game-changer. In today's fast-paced world, we leverage "
    "innovation seamlessly. At the end of the day, it's no secret that this matters."
)


async def _make_share(authed_client) -> str:
    """Run a real detection, then create a share link from its result."""
    det = await authed_client.post("/v1/detections", json={"text": _SAMPLE, "mode": "fast"})
    assert det.status_code == 201, det.text
    result = det.json()

    share = await authed_client.post("/v1/share", json={"result": result, "input_text": _SAMPLE})
    assert share.status_code == 201, share.text
    body = share.json()
    assert body["trial_limit"] == 3
    assert body["trial_used"] == 0
    assert body["url"].endswith(f"/r/{body['token']}")
    token: str = body["token"]
    return token


@pytest.mark.asyncio
async def test_share_requires_auth(client) -> None:
    resp = await client.post("/v1/share", json={"result": {"foo": "bar"}, "input_text": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_share_ignores_forged_result_payload(authed_client, client) -> None:
    det = await authed_client.post("/v1/detections", json={"text": _SAMPLE, "mode": "fast"})
    assert det.status_code == 201, det.text
    result = det.json()
    result["result"]["verdict"] = "ai"
    result["result"]["ai_probability"] = 1.0
    result["id"] = "00000000-0000-0000-0000-000000000000"
    result["request"]["text_hash"] = "sha256:forged"

    share = await authed_client.post(
        "/v1/share",
        json={"result": result, "input_text": _SAMPLE},
    )

    assert share.status_code == 201, share.text
    public = await client.get(f"/v1/share/{share.json()['token']}")
    assert public.status_code == 200, public.text
    shared_result = public.json()["result"]
    assert shared_result["id"] != "00000000-0000-0000-0000-000000000000"
    assert shared_result["request"]["text_hash"] != "sha256:forged"


@pytest.mark.asyncio
async def test_share_preserves_requested_detection_mode(authed_client, client) -> None:
    share = await authed_client.post(
        "/v1/share",
        json={"input_text": _SAMPLE, "mode": "thorough"},
    )
    assert share.status_code == 201, share.text

    public = await client.get(f"/v1/share/{share.json()['token']}")
    assert public.status_code == 200, public.text
    assert public.json()["result"]["metadata"]["mode"] == "thorough"


@pytest.mark.asyncio
async def test_get_share_public_returns_result(authed_client, client) -> None:
    token = await _make_share(authed_client)

    # Public read — no auth header.
    resp = await client.get(f"/v1/share/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"] == token
    assert body["active"] is True
    assert body["input_text"] == _SAMPLE
    assert body["result"]["object"] == "detection"
    assert body["trial_used"] == 0
    assert body["trial_limit"] == 3


@pytest.mark.asyncio
async def test_get_share_missing_404(client) -> None:
    resp = await client.get("/v1/share/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trial_consumes_then_exhausts(authed_client, client) -> None:
    token = await _make_share(authed_client)

    expected_remaining = [2, 1, 0]
    for i, remaining in enumerate(expected_remaining, start=1):
        resp = await client.post(f"/v1/share/{token}/trial", json={"text": _SAMPLE})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["trial_used"] == i
        assert body["remaining"] == remaining
        assert body["result"]["object"] == "detection"
        assert body["active"] is (remaining > 0)

    # 4th trial — exhausted.
    fourth = await client.post(f"/v1/share/{token}/trial", json={"text": _SAMPLE})
    assert fourth.status_code == 403
    assert fourth.json()["detail"] == EXHAUSTED

    # GET now reports the link as inactive.
    public = await client.get(f"/v1/share/{token}")
    assert public.status_code == 200
    assert public.json()["active"] is False


@pytest.mark.asyncio
async def test_invalid_trial_input_does_not_consume_quota(authed_client, client) -> None:
    token = await _make_share(authed_client)

    invalid = await client.post(
        f"/v1/share/{token}/trial",
        json={"text": _SAMPLE, "mode": "turbo"},
    )
    assert invalid.status_code == 422

    public = await client.get(f"/v1/share/{token}")
    assert public.status_code == 200
    assert public.json()["trial_used"] == 0
    assert public.json()["active"] is True

    valid = await client.post(f"/v1/share/{token}/trial", json={"text": _SAMPLE})
    assert valid.status_code == 201, valid.text
    assert valid.json()["trial_used"] == 1


@pytest.mark.asyncio
async def test_failed_trial_detection_refunds_quota(authed_client, client, monkeypatch) -> None:
    token = await _make_share(authed_client)

    from aidetect.api.v1 import share as share_module

    async def fail_detection(self, req, idempotency_key):
        raise RuntimeError("detector failed")

    monkeypatch.setattr(share_module.Orchestrator, "run", fail_detection)

    with pytest.raises(RuntimeError, match="detector failed"):
        await client.post(f"/v1/share/{token}/trial", json={"text": _SAMPLE})

    public = await client.get(f"/v1/share/{token}")
    assert public.status_code == 200
    assert public.json()["trial_used"] == 0
    assert public.json()["active"] is True


@pytest.mark.asyncio
async def test_trial_on_missing_token_404(client) -> None:
    resp = await client.post("/v1/share/nope/trial", json={"text": "hi"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revoked_link_blocks_trial_and_reports_inactive(
    authed_client, client, db_sessionmaker
) -> None:
    token = await _make_share(authed_client)

    from aidetect.db.models import ShareLink

    async with db_sessionmaker() as session:
        share = await session.get(ShareLink, token)
        assert share is not None
        share.revoked = True
        await session.commit()

    trial = await client.post(f"/v1/share/{token}/trial", json={"text": _SAMPLE})
    assert trial.status_code == 403
    assert trial.json()["detail"] == EXHAUSTED

    public = await client.get(f"/v1/share/{token}")
    assert public.status_code == 200
    assert public.json()["active"] is False
