from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AccessRequestIn(BaseModel):
    email: EmailStr
    share_token: str | None = None


class AccessRequestOut(BaseModel):
    status: str


class AccessRequestAdminOut(BaseModel):
    id: UUID
    email: str
    status: str
    source_share_token: str | None = None
    created_at: datetime
