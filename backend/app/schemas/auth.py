# -*- coding: utf-8 -*-
"""Схемы аутентификации по контракту docs/08 §2."""
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Role


class VesselBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    imo: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    login: str
    full_name: str
    role: Role
    is_active: bool
    vessels: list[VesselBrief] = Field(default_factory=list)


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    """Ответ POST /auth/token (docs/08 §2)."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int          # секунды жизни access-токена — клиенту удобно планировать refresh
    user: UserRead


class AccessTokenResponse(BaseModel):
    """Ответ POST /auth/refresh — только новый access."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
