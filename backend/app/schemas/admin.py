# -*- coding: utf-8 -*-
"""Схемы администрирования пользователей и судов (docs/08 §3)."""
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Role
from app.schemas.auth import UserRead


class Page(BaseModel):
    """Пагинация по docs/08 §1: ?page=&page_size= (по умолчанию 20)."""
    items: list
    total: int
    page: int
    page_size: int


# ── Пользователи (admin) ─────────────────────────────────────────────────────
class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=256)
    role: Role
    vessel_ids: list[uuid.UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: Role | None = None
    is_active: bool | None = None
    vessel_ids: list[uuid.UUID] | None = None


class UserPage(Page):
    items: list[UserRead]


# ── Суда (admin, fleet_owner) ────────────────────────────────────────────────
class VesselCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    imo: str | None = Field(default=None, max_length=32)
    type: str | None = Field(default=None, max_length=128)


class VesselUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    imo: str | None = Field(default=None, max_length=32)
    type: str | None = Field(default=None, max_length=128)


class VesselRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    imo: str | None = None
    type: str | None = None


class VesselPage(Page):
    items: list[VesselRead]
