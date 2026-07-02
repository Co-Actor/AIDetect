"""Async data-access helpers over an ``AsyncSession``.

Thin functions so routers stay declarative. Email is always normalised
(lowercased + stripped) before storage/lookup so the unique index is honoured
regardless of how the client cased it.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.db.models import AccessRequest, Detection, Invitation, ShareLink, User

# Synthetic account that owns detections/links created via the service API
# (internal-token auth). Non-routable email; cannot sign in (no password/google).
SERVICE_USER_EMAIL = "service@aidetect.local"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    """Coerce a DB-read datetime to tz-aware UTC.

    SQLite (tests) drops tzinfo on ``DateTime(timezone=True)`` columns, so values
    read back are naive; Postgres keeps them aware. Normalise to UTC so
    comparisons against ``datetime.now(UTC)`` never mix naive and aware.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def invitation_is_expired(inv: Invitation, *, now: datetime | None = None) -> bool:
    expires_at = _as_aware_utc(inv.expires_at)
    if expires_at is None:
        return False
    return (now or datetime.now(UTC)) > expires_at


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == _normalize_email(email))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_google_sub(session: AsyncSession, google_sub: str) -> User | None:
    stmt = select(User).where(User.google_sub == google_sub)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    name: str | None = None,
    password_hash: str | None = None,
    google_sub: str | None = None,
) -> User:
    user = User(
        email=_normalize_email(email),
        name=name,
        password_hash=password_hash,
        google_sub=google_sub,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def upsert_google_user(
    session: AsyncSession,
    *,
    google_sub: str,
    email: str,
    name: str | None = None,
) -> User:
    """Link a Google identity to a user, matching by ``google_sub`` then email.

    An existing email-only account gets its ``google_sub`` backfilled so the two
    sign-in paths converge on a single user row.
    """
    user = await get_user_by_google_sub(session, google_sub)
    if user is not None:
        return user

    user = await get_user_by_email(session, email)
    if user is not None:
        if user.google_sub is None:
            user.google_sub = google_sub
        if user.name is None and name is not None:
            user.name = name
        await session.commit()
        await session.refresh(user)
        return user

    return await create_user(session, email=email, name=name, google_sub=google_sub)


async def get_or_create_service_user(session: AsyncSession) -> User:
    """Return the shared service account, creating it on first use.

    Race-safe: a concurrent first call may win the insert, so a unique-violation
    falls back to fetching the row the other request created.
    """
    user = await get_user_by_email(session, SERVICE_USER_EMAIL)
    if user is not None:
        return user
    try:
        return await create_user(session, email=SERVICE_USER_EMAIL, name="Service (API)")
    except IntegrityError:
        await session.rollback()
        existing = await get_user_by_email(session, SERVICE_USER_EMAIL)
        if existing is None:  # pragma: no cover — only reachable on a real race
            raise
        return existing


async def list_users(session: AsyncSession) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc())
    return list((await session.execute(stmt)).scalars())


async def set_user_admin(session: AsyncSession, user: User, value: bool) -> None:
    user.is_admin = value
    await session.commit()
    await session.refresh(user)


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete a user with their detections + share links.

    Dialect-agnostic: explicit child deletes work on both SQLite (tests, no FK
    enforcement) and Postgres (prod), independent of ON DELETE CASCADE.
    """
    await session.execute(delete(ShareLink).where(ShareLink.user_id == user_id))
    await session.execute(delete(Detection).where(Detection.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


async def create_detection(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    input_text: str,
    result_json: dict[str, object],
) -> Detection:
    detection = Detection(user_id=user_id, input_text=input_text, result_json=result_json)
    session.add(detection)
    await session.commit()
    await session.refresh(detection)
    return detection


async def create_share_link(
    session: AsyncSession,
    *,
    detection: Detection,
    user_id: uuid.UUID,
    trial_limit: int,
) -> ShareLink:
    share = ShareLink(
        token=secrets.token_urlsafe(16),
        detection_id=detection.id,
        user_id=user_id,
        trial_used=0,
        trial_limit=trial_limit,
        revoked=False,
    )
    session.add(share)
    await session.commit()
    await session.refresh(share)
    return share


async def get_share_link(session: AsyncSession, token: str) -> ShareLink | None:
    return await session.get(ShareLink, token)


async def get_detection_for_share(session: AsyncSession, share: ShareLink) -> Detection:
    """Load the Detection a share link points at (always present via FK)."""
    detection = await session.get(Detection, share.detection_id)
    if detection is None:  # pragma: no cover — FK guarantees existence
        raise RuntimeError(f"detection {share.detection_id} missing for share {share.token}")
    return detection


async def try_consume_trial(session: AsyncSession, token: str) -> int | None:
    """Atomically consume one trial check.

    Single guarded UPDATE … RETURNING so concurrent requests can never push
    ``trial_used`` past ``trial_limit``. Returns the new ``trial_used`` on
    success, or ``None`` when the link is exhausted, revoked, or missing.
    """
    stmt = (
        update(ShareLink)
        .where(
            ShareLink.token == token,
            ShareLink.trial_used < ShareLink.trial_limit,
            ShareLink.revoked.is_(False),
        )
        .values(trial_used=ShareLink.trial_used + 1)
        .returning(ShareLink.trial_used)
    )
    result = await session.execute(stmt)
    new_used = result.scalar_one_or_none()
    await session.commit()
    return new_used


async def refund_trial(session: AsyncSession, token: str) -> None:
    """Return one consumed trial check after a failed detection attempt."""
    stmt = (
        update(ShareLink)
        .where(ShareLink.token == token, ShareLink.trial_used > 0)
        .values(trial_used=ShareLink.trial_used - 1)
    )
    await session.execute(stmt)
    await session.commit()


# ── Invitations ──────────────────────────────────────────────────────


async def create_invitation(
    session: AsyncSession,
    *,
    email: str,
    invited_by: uuid.UUID | None,
    expires_at: datetime | None,
) -> Invitation:
    invitation = Invitation(
        email=_normalize_email(email),
        token=secrets.token_urlsafe(24),
        status="pending",
        invited_by=invited_by,
        expires_at=expires_at,
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)
    return invitation


async def get_invitation_by_token(session: AsyncSession, token: str) -> Invitation | None:
    stmt = select(Invitation).where(Invitation.token == token)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_pending_invitation_by_email(session: AsyncSession, email: str) -> Invitation | None:
    """Return a still-valid pending invitation for an email, or None.

    Expired pending invitations are treated as absent.
    """
    stmt = select(Invitation).where(
        Invitation.email == _normalize_email(email),
        Invitation.status == "pending",
    )
    now = datetime.now(UTC)
    for invitation in (await session.execute(stmt)).scalars():
        if invitation_is_expired(invitation, now=now):
            continue
        return invitation
    return None


async def accept_invitation(session: AsyncSession, inv: Invitation) -> None:
    inv.status = "accepted"
    inv.accepted_at = datetime.now(UTC)
    await session.commit()


async def list_invitations(session: AsyncSession) -> list[Invitation]:
    stmt = select(Invitation).order_by(Invitation.created_at.desc())
    return list((await session.execute(stmt)).scalars())


# ── Access requests ──────────────────────────────────────────────────


async def create_access_request(
    session: AsyncSession,
    *,
    email: str,
    source_share_token: str | None,
) -> AccessRequest:
    request = AccessRequest(
        email=_normalize_email(email),
        status="pending",
        source_share_token=source_share_token,
    )
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return request


async def get_pending_access_request_by_email(
    session: AsyncSession, email: str
) -> AccessRequest | None:
    stmt = select(AccessRequest).where(
        AccessRequest.email == _normalize_email(email),
        AccessRequest.status == "pending",
    )
    return (await session.execute(stmt)).scalars().first()


async def get_active_access_request_by_email(
    session: AsyncSession, email: str
) -> AccessRequest | None:
    stmt = select(AccessRequest).where(
        AccessRequest.email == _normalize_email(email),
        AccessRequest.status.in_(("pending", "invited")),
    )
    return (await session.execute(stmt)).scalars().first()


async def list_access_requests(session: AsyncSession) -> list[AccessRequest]:
    stmt = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    return list((await session.execute(stmt)).scalars())


async def get_access_request(session: AsyncSession, id: uuid.UUID) -> AccessRequest | None:
    return await session.get(AccessRequest, id)


async def mark_request_invited(session: AsyncSession, req: AccessRequest) -> None:
    req.status = "invited"
    await session.commit()
