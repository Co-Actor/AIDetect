from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.api.deps import SettingsDep
from aidetect.config import Settings
from aidetect.db.models import Invitation, User
from aidetect.db.session import get_db_session
from aidetect.schemas.auth import (
    AuthResponse,
    GoogleRequest,
    InvitationCheckOut,
    LoginRequest,
    RegisterRequest,
    UserOut,
)
from aidetect.services import repository
from aidetect.services.auth import (
    CurrentUserDep,
    create_access_token,
    hash_password,
    is_user_admin,
    verify_password,
)
from aidetect.services.google_oauth import verify_google_id_token

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

_INVITE_ONLY = "registration is invite-only"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _invitation_is_valid(inv: Invitation | None) -> bool:
    if inv is None or inv.status != "pending":
        return False
    return not repository.invitation_is_expired(inv)


async def _ensure_admin_flag(session: AsyncSession, user: User, settings: Settings) -> None:
    """Self-heal: promote a user to admin when their email is in ADMIN_EMAILS."""
    if not user.is_admin and _normalize_email(user.email) in settings.admin_emails_set:
        await repository.set_user_admin(session, user, True)


def _auth_response(user: User, settings: Settings) -> AuthResponse:
    token = create_access_token(user.id, settings)
    return AuthResponse(
        token=token,
        user=UserOut(
            id=user.id,
            email=user.email,
            name=user.name,
            is_admin=is_user_admin(user, settings),
        ),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    settings: SettingsDep,
    session: DbSession,
) -> AuthResponse:
    invitation: Invitation | None = None
    if not settings.registration_open:
        if not payload.invite_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_ONLY)
        invitation = await repository.get_invitation_by_token(session, payload.invite_token)
        if not _invitation_is_valid(invitation) or (
            invitation is not None and invitation.email != _normalize_email(payload.email)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="invalid or expired invitation",
            )

    existing = await repository.get_user_by_email(session, payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered",
        )
    try:
        user = await repository.create_user(
            session,
            email=payload.email,
            name=payload.name,
            password_hash=hash_password(payload.password),
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered",
        ) from exc
    if invitation is not None:
        await repository.accept_invitation(session, invitation)
    await _ensure_admin_flag(session, user, settings)
    return _auth_response(user, settings)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    settings: SettingsDep,
    session: DbSession,
) -> AuthResponse:
    user = await repository.get_user_by_email(session, payload.email)
    if (
        user is None
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )
    await _ensure_admin_flag(session, user, settings)
    return _auth_response(user, settings)


@router.post("/google", response_model=AuthResponse)
async def google_sign_in(
    payload: GoogleRequest,
    settings: SettingsDep,
    session: DbSession,
) -> AuthResponse:
    identity = await verify_google_id_token(payload.id_token, settings)

    # Existing-user sign-in is always allowed; backfill google_sub on an
    # email-only account so the two sign-in paths converge on one row.
    user = await repository.get_user_by_google_sub(session, identity.sub)
    if user is None:
        user = await repository.get_user_by_email(session, identity.email)
    if user is not None:
        if user.google_sub is None:
            user.google_sub = identity.sub
        if user.name is None and identity.name is not None:
            user.name = identity.name
        await session.commit()
        await session.refresh(user)
        await _ensure_admin_flag(session, user, settings)
        return _auth_response(user, settings)

    # New account — gated behind an open registration or a pending invitation.
    invitation = await repository.get_pending_invitation_by_email(session, identity.email)
    if not settings.registration_open and invitation is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_ONLY)

    user = await repository.create_user(
        session,
        email=identity.email,
        name=identity.name,
        google_sub=identity.sub,
    )
    if invitation is not None:
        await repository.accept_invitation(session, invitation)
    await _ensure_admin_flag(session, user, settings)
    return _auth_response(user, settings)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUserDep, settings: SettingsDep) -> UserOut:
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_admin=is_user_admin(current_user, settings),
    )


@router.get("/invitations/{token}", response_model=InvitationCheckOut)
async def check_invitation(token: str, session: DbSession) -> InvitationCheckOut:
    invitation = await repository.get_invitation_by_token(session, token)
    return InvitationCheckOut(
        email=invitation.email if invitation is not None else None,
        valid=_invitation_is_valid(invitation),
    )
