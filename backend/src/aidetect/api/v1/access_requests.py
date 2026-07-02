"""Public endpoint for requesting access (join the waitlist).

Idempotent and privacy-preserving: it always returns ``{status: "received"}``
and never reveals whether the email is already registered or already queued.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.db.session import get_db_session
from aidetect.schemas.access import AccessRequestIn, AccessRequestOut
from aidetect.services import repository

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post("", response_model=AccessRequestOut, status_code=status.HTTP_201_CREATED)
async def create_access_request(
    payload: AccessRequestIn,
    session: DbSession,
) -> AccessRequestOut:
    email = _normalize_email(payload.email)
    already_user = await repository.get_user_by_email(session, email) is not None
    already_queued = await repository.get_active_access_request_by_email(session, email) is not None
    if not already_user and not already_queued:
        await repository.create_access_request(
            session, email=email, source_share_token=payload.share_token
        )
    return AccessRequestOut(status="received")
