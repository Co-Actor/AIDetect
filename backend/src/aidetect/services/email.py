"""Transactional email sending via Resend.

No-op when unconfigured: with no ``RESEND_API_KEY`` the sender logs the intended
message and returns without touching the network, so local/dev/test flows never
depend on an outbound mail provider. Email delivery is best-effort — a failed
send is logged and swallowed so it can never turn an admin call into a 500 (the
invitation row is already persisted by the time we get here).
"""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import Depends

from aidetect.api.deps import SettingsDep
from aidetect.config import Settings

logger = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"
_TIMEOUT = 10.0


def _invitation_html(invite_url: str) -> str:
    return (
        "<p>You've been invited to AIDetect.</p>"
        f'<p><a href="{invite_url}">Accept your invitation</a></p>'
        f"<p>Or open this link: {invite_url}</p>"
    )


class EmailSender:
    """Interface for sending transactional emails."""

    async def send_invitation(self, email: str, invite_url: str) -> None:
        raise NotImplementedError


class ResendEmailSender(EmailSender):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_invitation(self, email: str, invite_url: str) -> None:
        api_key = self._settings.resend_api_key
        if not api_key:
            logger.info("[email disabled] invitation for %s -> %s", email, invite_url)
            return
        payload = {
            "from": self._settings.email_from,
            "to": [email],
            "subject": "You're invited to AIDetect",
            "html": _invitation_html(invite_url),
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(_RESEND_ENDPOINT, json=payload, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            # Best-effort: never propagate — the invitation is already created.
            logger.warning("failed to send invitation email to %s: %s", email, exc)


def get_email_sender(settings: SettingsDep) -> EmailSender:
    return ResendEmailSender(settings)


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
