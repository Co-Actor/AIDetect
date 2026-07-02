from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class InviteRequest(BaseModel):
    email: EmailStr


class InviteOut(BaseModel):
    email: str
    url: str
    token: str
    status: str


class InvitationOut(BaseModel):
    id: UUID
    email: str
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    accepted_at: datetime | None = None
