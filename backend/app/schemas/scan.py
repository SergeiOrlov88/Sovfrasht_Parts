# -*- coding: utf-8 -*-
"""Схемы сканов и отчёта (docs/08 §4)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PhotoKind, RecognitionStatus, ScanStatus


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class ScanCreateMeta(BaseModel):
    """JSON-часть multipart-запроса POST /scans."""
    vessel_id: uuid.UUID
    geo: GeoPoint | None = None
    # Клиентский ключ идемпотентности (NFR-REL-04)
    client_scan_id: str | None = Field(default=None, max_length=128)


class ScanAccepted(BaseModel):
    """Ответ 202: задача принята в обработку."""
    scan_id: uuid.UUID
    status: ScanStatus
    # true, если скан с таким client_scan_id уже существовал и новый не создавался
    idempotent_reuse: bool = False


class PhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: PhotoKind
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    # Подписанная ссылка с истечением (NFR-SEC-04); прямого доступа к бакету нет
    url: str | None = None


class ScanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vessel_id: uuid.UUID
    author_id: uuid.UUID
    status: ScanStatus
    created_at: datetime
    photos: list[PhotoRead] = Field(default_factory=list)


class RecognitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    part_id: uuid.UUID | None = None
    confidence: int | None = None
    ocr_text: str | None = None
    maker_detected: str | None = None
    oem_detected: str | None = None
    model_version: str | None = None
    status: RecognitionStatus


class ScanReport(BaseModel):
    """Отчёт по скану. Сопоставление с каталогом и кандидаты — шаг 3 (A3)."""
    scan_id: uuid.UUID
    status: ScanStatus
    created_at: datetime
    recognition: RecognitionRead | None = None
    photos: list[PhotoRead] = Field(default_factory=list)
    # Ниже порога результат не годится для автоматического оформления заявки
    # (FR-REC-04, NFR-ACC-03)
    needs_expert: bool = False
    message: str | None = None
