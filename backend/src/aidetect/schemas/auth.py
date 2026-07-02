from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str | None = None
    invite_token: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleRequest(BaseModel):
    id_token: str


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str | None = None
    is_admin: bool = False


class UserAdminOut(BaseModel):
    id: UUID
    email: str
    name: str | None = None
    is_admin: bool
    created_at: datetime


class UserRoleUpdate(BaseModel):
    is_admin: bool


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class InvitationCheckOut(BaseModel):
    email: str | None
    valid: bool
