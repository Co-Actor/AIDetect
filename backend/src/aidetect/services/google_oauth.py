"""Google Sign-In ID-token verification.

Wraps the synchronous ``google.oauth2.id_token.verify_oauth2_token`` (which
fetches/caches Google's signing certs) in a worker thread so it never blocks the
event loop. Sign-in is opt-in: with no configured client id every call 400s.
"""

from __future__ import annotations

from dataclasses import dataclass

import anyio.to_thread
import google.auth.transport.requests
from fastapi import HTTPException, status
from google.oauth2 import id_token as google_id_token

from aidetect.config import Settings


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None


def _verify_sync(id_token_str: str, client_id: str) -> dict[str, object]:
    request = google.auth.transport.requests.Request()
    # google-auth ships no type information for verify_oauth2_token, so mypy sees
    # it as an untyped call. The returned mapping of verified claims is narrowed
    # by the explicit annotation below.
    result: dict[str, object] = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
        id_token_str, request, client_id
    )
    return result


async def verify_google_id_token(id_token_str: str, settings: Settings) -> GoogleIdentity:
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google sign-in is not configured",
        )
    try:
        claims = await anyio.to_thread.run_sync(
            _verify_sync, id_token_str, settings.google_oauth_client_id
        )
    except Exception as exc:  # any verification failure → 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google token",
        ) from exc

    sub = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified")
    if not sub or not email or email_verified is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google token",
        )
    name = claims.get("name")
    return GoogleIdentity(
        sub=str(sub),
        email=str(email),
        name=str(name) if name is not None else None,
    )
