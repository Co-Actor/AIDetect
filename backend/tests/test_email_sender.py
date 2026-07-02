from __future__ import annotations

import pytest

from aidetect.config import Settings
from aidetect.services.email import ResendEmailSender


@pytest.mark.asyncio
async def test_send_invitation_noop_when_unconfigured() -> None:
    # With no RESEND_API_KEY the sender must not touch the network and must not
    # raise — it just logs the intended invite URL.
    settings = Settings(resend_api_key=None)
    sender = ResendEmailSender(settings)
    result = await sender.send_invitation("someone@example.com", "http://app/register?invite=abc")
    assert result is None


@pytest.mark.asyncio
async def test_send_invitation_noop_logs(caplog) -> None:
    settings = Settings(resend_api_key="")
    sender = ResendEmailSender(settings)
    with caplog.at_level("INFO"):
        await sender.send_invitation("logme@example.com", "http://app/register?invite=xyz")
    assert any("logme@example.com" in record.getMessage() for record in caplog.records)
