"""Append-only JSONL feedback writer.

Each line is a self-describing JSON object so the file can be tailed, grep'd,
and ingested by the calibration pipeline without a schema migration. When usage
grows past a few thousand entries we'll move this to a real store.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


async def append_feedback(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(UTC).isoformat(), **payload}
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    async with _lock:
        await asyncio.to_thread(_append_sync, target, line)


def _append_sync(target: Path, line: str) -> None:
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line)
