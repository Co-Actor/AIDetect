from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.api.deps import SettingsDep
from aidetect.db.models import User
from aidetect.db.session import get_db_session
from aidetect.schemas.auth import (
    AuthResponse,
    GoogleRequest,
    LoginRequest,
    RegisterRequest,
    UserOut,
)
from aidetect.services import repository
from aidetect.services.auth import (
    CurrentUserDep,
    create_access_token,
    hash_password,
    verify_password,
)
from aidetect.services.google_oauth import verify_google_id_token

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _auth_response(user: User, settings: SettingsDep) -> AuthResponse:
    token = create_access_token(user.id, settings)
    return AuthResponse(
        token=token,
        user=UserOut(id=user.id, email=user.email, name=user.name),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    settings: SettingsDep,
    session: DbSession,
) -> AuthResponse:
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
    return _auth_response(user, settings)


@router.post("/google", response_model=AuthResponse)
async def google_sign_in(
    payload: GoogleRequest,
    settings: SettingsDep,
    session: DbSession,
) -> AuthResponse:
    identity = await verify_google_id_token(payload.id_token, settings)
    user = await repository.upsert_google_user(
        session,
        google_sub=identity.sub,
        email=identity.email,
        name=identity.name,
    )
    return _auth_response(user, settings)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUserDep) -> UserOut:
    return UserOut(id=current_user.id, email=current_user.email, name=current_user.name)
