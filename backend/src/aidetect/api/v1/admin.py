"""Admin endpoints for managing invitations, access requests and users.

Guarded by ``AdminDep`` — the internal service token (scripts / e2e) OR a JWT
belonging to an admin user (the in-app admin panel).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.api.deps import SettingsDep
from aidetect.config import Settings
from aidetect.db.models import Invitation, User
from aidetect.db.session import get_db_session
from aidetect.schemas.access import AccessRequestAdminOut
from aidetect.schemas.auth import UserAdminOut, UserRoleUpdate
from aidetect.schemas.invite import InvitationOut, InviteOut, InviteRequest
from aidetect.services import repository
from aidetect.services.auth import AdminActorDep, AdminDep, is_user_admin
from aidetect.services.email import EmailSenderDep

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _invite_url(settings: Settings, token: str) -> str:
    return f"{settings.app_base_url}/register?invite={token}"


def _invite_out(settings: Settings, inv: Invitation) -> InviteOut:
    return InviteOut(
        email=inv.email,
        url=_invite_url(settings, inv.token),
        token=inv.token,
        status=inv.status,
    )


async def _issue_invitation(session: AsyncSession, settings: Settings, email: str) -> Invitation:
    """Reuse a live pending invitation for an email, or mint a fresh one.

    Caller must have already ruled out an existing user for the email.
    """
    existing = await repository.get_pending_invitation_by_email(session, email)
    if existing is not None:
        return existing
    expires_at = datetime.now(UTC) + timedelta(days=settings.invite_expire_days)
    return await repository.create_invitation(
        session, email=email, invited_by=None, expires_at=expires_at
    )


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    settings: SettingsDep,
    session: DbSession,
    _: AdminDep,
) -> list[UserAdminOut]:
    users = await repository.list_users(session)
    return [
        UserAdminOut(
            id=user.id,
            email=user.email,
            name=user.name,
            is_admin=is_user_admin(user, settings),
            created_at=user.created_at,
        )
        for user in users
    ]


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def set_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    settings: SettingsDep,
    session: DbSession,
    actor: AdminActorDep,
) -> UserAdminOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if actor is not None and actor.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot change your own admin role",
        )
    if not payload.is_admin and _normalize_email(user.email) in settings.admin_emails_set:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user is an admin via ADMIN_EMAILS; remove them from ADMIN_EMAILS to demote",
        )
    await repository.set_user_admin(session, user, payload.is_admin)
    return UserAdminOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=is_user_admin(user, settings),
        created_at=user.created_at,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    session: DbSession,
    actor: AdminActorDep,
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if actor is not None and actor.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete your own account",
        )
    if user.email == repository.SERVICE_USER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete the service account",
        )
    await repository.delete_user(session, user_id)


@router.post("/invitations", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InviteRequest,
    settings: SettingsDep,
    session: DbSession,
    email_sender: EmailSenderDep,
    _: AdminDep,
) -> InviteOut:
    email = _normalize_email(payload.email)
    if await repository.get_user_by_email(session, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user already exists")
    invitation = await _issue_invitation(session, settings, email)
    url = _invite_url(settings, invitation.token)
    await email_sender.send_invitation(invitation.email, url)
    return _invite_out(settings, invitation)


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(session: DbSession, _: AdminDep) -> list[InvitationOut]:
    invitations = await repository.list_invitations(session)
    return [InvitationOut.model_validate(inv, from_attributes=True) for inv in invitations]


@router.get("/access-requests", response_model=list[AccessRequestAdminOut])
async def list_access_requests(session: DbSession, _: AdminDep) -> list[AccessRequestAdminOut]:
    requests = await repository.list_access_requests(session)
    return [AccessRequestAdminOut.model_validate(req, from_attributes=True) for req in requests]


@router.post(
    "/access-requests/{request_id}/invite",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_access_request(
    request_id: UUID,
    settings: SettingsDep,
    session: DbSession,
    email_sender: EmailSenderDep,
    _: AdminDep,
) -> InviteOut:
    request = await repository.get_access_request(session, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="access request not found")
    if await repository.get_user_by_email(session, request.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user already exists")
    invitation = await _issue_invitation(session, settings, request.email)
    url = _invite_url(settings, invitation.token)
    await email_sender.send_invitation(invitation.email, url)
    await repository.mark_request_invited(session, request)
    return _invite_out(settings, invitation)
