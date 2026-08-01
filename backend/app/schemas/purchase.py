# -*- coding: utf-8 -*-
"""Схемы закупки: предложения (C1) и заявки (C2), docs/08 §5."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RequestPriority, RequestStatus, StockStatus, SupplierType
from app.schemas.scan import PartBrief


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    type: SupplierType
    url: str | None = None
    region: str | None = None


class OfferRead(BaseModel):
    """Предложение поставщика (FR-PRO-01/02)."""
    supplier: SupplierRead
    price: str | None = None
    lead_time: str | None = None
    stock_status: StockStatus | None = None
    deep_link: str | None = None
    # curated | demo | api — на MVP всё демонстрационное, это должно быть видно
    source: str = "curated"
    fetched_at: datetime | None = None


class AlternativeOffers(BaseModel):
    """Предложения по аналогу детали."""
    part: PartBrief
    compatibility: str
    offers: list[OfferRead] = Field(default_factory=list)


class PartOffers(BaseModel):
    part: PartBrief
    offers: list[OfferRead] = Field(default_factory=list)
    alternatives: list[AlternativeOffers] = Field(default_factory=list)
    message: str | None = None


# ── Заявки (C2) ──────────────────────────────────────────────────────────────

class PartRequestCreate(BaseModel):
    part_id: uuid.UUID
    vessel_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=9999)
    priority: RequestPriority = RequestPriority.normal
    comment: str | None = Field(default=None, max_length=2000)
    # Связь с распознаванием: по нему проверяется порог достоверности (FR-REC-04)
    recognition_id: uuid.UUID | None = None
    # Клиентский ключ идемпотентности (NFR-REL-04)
    client_request_id: str | None = Field(default=None, max_length=128)


class PartRequestRead(BaseModel):
    id: uuid.UUID
    part: PartBrief | None = None
    vessel_id: uuid.UUID
    vessel_name: str | None = None
    author_id: uuid.UUID
    recognition_id: uuid.UUID | None = None
    quantity: int
    priority: RequestPriority
    status: RequestStatus
    comment: str | None = None
    created_at: datetime
    # Куда заявку можно перевести из текущего статуса (FR-PRO-04)
    next_statuses: list[str] = Field(default_factory=list)
    idempotent_reuse: bool = False


class PartRequestStatusUpdate(BaseModel):
    status: RequestStatus


class PartRequestPage(BaseModel):
    items: list[PartRequestRead]
    total: int
    page: int
    page_size: int
