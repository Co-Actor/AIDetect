from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.api.deps import AuthDep, SettingsDep
from aidetect.config import Settings
from aidetect.db.session import get_db_session
from aidetect.schemas.detection import DetectionRequest
from aidetect.schemas.share import (
    CreateShareRequest,
    DetectLinkOut,
    DetectLinkRequest,
    ShareCreatedOut,
    SharePublicOut,
    TrialRequest,
    TrialResultOut,
)
from aidetect.services import repository
from aidetect.services.auth import CurrentUserDep
from aidetect.services.cache import get_cache
from aidetect.services.orchestrator import Orchestrator

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _exhausted_message(limit: int) -> str:
    return f"You've used all {limit} free checks. Sign up to keep using AIDetect."


# Public default for the canonical 3-check limit (used in tests/contract).
EXHAUSTED_MESSAGE = _exhausted_message(3)


@router.post("", response_model=ShareCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_share(
    payload: CreateShareRequest,
    settings: SettingsDep,
    session: DbSession,
    current_user: CurrentUserDep,
) -> ShareCreatedOut:
    result_json = await _run_detection(payload.input_text, payload.mode, settings)
    detection = await repository.create_detection(
        session,
        user_id=current_user.id,
        input_text=payload.input_text,
        result_json=result_json,
    )
    share = await repository.create_share_link(
        session,
        detection=detection,
        user_id=current_user.id,
        trial_limit=settings.trial_check_limit,
    )
    return ShareCreatedOut(
        token=share.token,
        url=f"{settings.app_base_url}/r/{share.token}",
        trial_limit=share.trial_limit,
        trial_used=share.trial_used,
    )


@router.post("/detect-link", response_model=DetectLinkOut, status_code=status.HTTP_201_CREATED)
async def detect_and_link(
    payload: DetectLinkRequest,
    settings: SettingsDep,
    session: DbSession,
    _auth: AuthDep,
) -> DetectLinkOut:
    """Service API: analyze a text and return a shareable result link in one call.

    Authenticated with the internal token (header ``X-API-Key``). The link is
    owned by the service account and carries the usual trial-check quota for
    whoever opens it.
    """
    result_json = await _run_detection(payload.text, payload.mode, settings, payload.language)
    service_user = await repository.get_or_create_service_user(session)
    detection = await repository.create_detection(
        session,
        user_id=service_user.id,
        input_text=payload.text,
        result_json=result_json,
    )
    share = await repository.create_share_link(
        session,
        detection=detection,
        user_id=service_user.id,
        trial_limit=settings.trial_check_limit,
    )
    return DetectLinkOut(
        url=f"{settings.app_base_url}/r/{share.token}",
        token=share.token,
        trial_limit=share.trial_limit,
        result=result_json,
    )


@router.get("/{token}", response_model=SharePublicOut)
async def get_share(token: str, session: DbSession) -> SharePublicOut:
    share = await repository.get_share_link(session, token)
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="share link not found")
    detection = await repository.get_detection_for_share(session, share)
    active = (not share.revoked) and share.trial_used < share.trial_limit
    return SharePublicOut(
        token=share.token,
        result=detection.result_json,
        input_text=detection.input_text,
        trial_used=share.trial_used,
        trial_limit=share.trial_limit,
        active=active,
    )


@router.post("/{token}/trial", response_model=TrialResultOut, status_code=status.HTTP_201_CREATED)
async def run_trial(
    token: str,
    payload: TrialRequest,
    settings: SettingsDep,
    session: DbSession,
) -> TrialResultOut:
    share = await repository.get_share_link(session, token)
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="share link not found")

    req = _build_detection_request(payload.text, payload.mode, settings)
    new_used = await repository.try_consume_trial(session, token)
    if new_used is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_exhausted_message(share.trial_limit),
        )

    try:
        result = await _run_detection_request(req, settings)
    except Exception:
        await repository.refund_trial(session, token)
        raise

    remaining = share.trial_limit - new_used
    return TrialResultOut(
        result=result,
        trial_used=new_used,
        trial_limit=share.trial_limit,
        remaining=remaining,
        active=remaining > 0,
    )


async def _run_detection(
    text: str,
    mode: str | None,
    settings: Settings,
    language: str | None = None,
) -> dict[str, object]:
    req = _build_detection_request(text, mode, settings, language)
    return await _run_detection_request(req, settings)


def _build_detection_request(
    text: str,
    mode: str | None,
    settings: Settings,
    language: str | None = None,
) -> DetectionRequest:
    try:
        req = DetectionRequest(
            text=text,
            mode=mode or settings.default_mode,
            language=language or "auto",
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(),
        ) from exc
    if len(req.text) > settings.max_text_length:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"text exceeds MAX_TEXT_LENGTH={settings.max_text_length}",
        )
    return req


async def _run_detection_request(
    req: DetectionRequest,
    settings: Settings,
) -> dict[str, object]:
    cache = await get_cache(settings)
    orchestrator = Orchestrator(settings=settings, cache=cache)
    response = await orchestrator.run(req, idempotency_key=None)
    return response.model_dump(mode="json")
