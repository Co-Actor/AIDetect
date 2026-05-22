from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_feedback_appends_jsonl(client, auth_headers) -> None:
    payload = {
        "detection_id": str(uuid.uuid4()),
        "label": "incorrect",
        "note": "false positive on a translated quote",
    }
    resp = await client.post("/v1/feedback", headers=auth_headers, json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["label"] == "incorrect"
    assert body["detection_id"] == payload["detection_id"]

    log_path = Path(os.environ["FEEDBACK_LOG_PATH"])
    assert log_path.exists(), "feedback.jsonl was not created"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["label"] == "incorrect"
    assert record["detection_id"] == payload["detection_id"]
    assert "ts" in record
