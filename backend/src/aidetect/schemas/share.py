from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from aidetect.schemas.detection import Mode


class CreateShareRequest(BaseModel):
    input_text: str
    mode: Mode | None = None
    # Back-compat for older frontend builds. The server never trusts or stores
    # caller-supplied results; it re-runs detection before publishing.
    result: dict[str, object] | None = None


class ShareCreatedOut(BaseModel):
    token: str
    url: str
    trial_limit: int
    trial_used: int


class SharePublicOut(BaseModel):
    token: str
    result: dict[str, object]
    input_text: str
    trial_used: int
    trial_limit: int
    active: bool


class TrialRequest(BaseModel):
    text: str
    mode: str | None = None


class TrialResultOut(BaseModel):
    result: dict[str, object]
    trial_used: int
    trial_limit: int
    remaining: int
    active: bool


class DetectLinkRequest(BaseModel):
    """Service API: analyze a text and mint a shareable result link in one call."""

    text: str
    # Optional; defaults to "balanced" regardless of the server-wide DEFAULT_MODE.
    mode: Literal["fast", "balanced", "thorough"] = "balanced"
    language: str | None = None


class DetectLinkOut(BaseModel):
    url: str
    token: str
    trial_limit: int
    result: dict[str, object]
