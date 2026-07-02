"""Password hashing, JWT minting/decoding, and the current-user dependency."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.config import Settings, get_settings
from aidetect.db.models import User
from aidetect.db.session import get_db_session

_JWT_ALG = "HS256"


def _bcrypt_bytes(password: str) -> bytes:
    # bcrypt only consumes the first 72 bytes and bcrypt>=4 raises past that.
    # Truncate to 72 bytes (its long-standing behavior) so a long password-manager
    # password doesn't 500. Applied symmetrically to hashing and verification.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_bytes(password), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/empty hash (e.g. a Google-only account) — never matches.
        return False


def create_access_token(user_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.auth_jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=_JWT_ALG)


def decode_token(token: str, settings: Settings) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.auth_jwt_secret, algorithms=[_JWT_ALG])
        return uuid.UUID(str(payload["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        ) from exc


async def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_token(token, settings)
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def is_user_admin(user: User, settings: Settings) -> bool:
    """True when the user holds the admin role (DB flag or configured email)."""
    return user.is_admin or user.email.strip().lower() in settings.admin_emails_set


async def get_admin_actor(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """Authorize an admin request and return the acting user.

    Returns the admin ``User`` for a JWT caller, or ``None`` for the internal
    service token (scripts / CI carry no user identity). Missing credentials →
    401; present-but-insufficient → 403 (mirrors the internal-token dependency
    the admin router used before).
    """
    internal = settings.aidetect_internal_token
    forbidden = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="admin access required"
    )
    if x_api_key:
        if secrets.compare_digest(x_api_key, internal):
            return None
        raise forbidden
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token and secrets.compare_digest(token, internal):
            return None
        user_id = decode_token(token, settings)
        user = await session.get(User, user_id)
        if user is not None and is_user_admin(user, settings):
            return user
        raise forbidden
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
    )


async def require_admin(_actor: Annotated[User | None, Depends(get_admin_actor)]) -> None:
    """Authorize an admin request (internal token or admin JWT); discard identity."""


AdminActorDep = Annotated[User | None, Depends(get_admin_actor)]
AdminDep = Annotated[None, Depends(require_admin)]
