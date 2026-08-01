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


class PartBrief(BaseModel):
    """Позиция каталога в отчёте (FR-REP-01)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    maker: str | None = None
    category: str | None = None
    impa_code: str | None = None
    issa_code: str | None = None
    oem_number: str | None = None
    equipment: str | None = None
    specs: dict | None = None


class AlternativeRead(BaseModel):
    """Аналог/заменитель детали (FR-REP-03, FR-CAT-04)."""
    part: "PartBrief"
    compatibility: str          # full | partial | kit
    note: str | None = None


class CandidateRead(BaseModel):
    """Альтернативный кандидат с релевантностью (NFR-ACC-02)."""
    part: PartBrief
    relevance: float


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
    # matched | candidates | not_found — «нет в каталоге» показывается честно,
    # похожее силой не подбирается (решение заказчика)
    catalog_status: str | None = None


class ScanReport(BaseModel):
    """Полный отчёт по скану (B1, FR-REP-01..03)."""
    scan_id: uuid.UUID
    # Нужен вкладке «Закупка»: заявка оформляется на конкретное судно
    vessel_id: uuid.UUID
    status: ScanStatus
    created_at: datetime
    recognition: RecognitionRead | None = None
    part: PartBrief | None = None                     # найденная позиция каталога
    candidates: list[CandidateRead] = Field(default_factory=list)
    alternatives: list[AlternativeRead] = Field(default_factory=list)   # FR-REP-03
    photos: list[PhotoRead] = Field(default_factory=list)
    # Ниже порога результат не годится для автоматического оформления заявки
    # (FR-REC-04, NFR-ACC-03)
    needs_expert: bool = False
    # Индикатор достоверности и предупреждение (FR-REP-02)
    confidence: int | None = None
    confidence_level: str | None = None               # high | medium | low
    warning: str | None = None
    # Доступные пользователю действия по отчёту
    can_confirm: bool = False
    can_request_expert: bool = False
    feedback: "FeedbackState | None" = None
    message: str | None = None


class FeedbackState(BaseModel):
    """Что пользователь уже ответил по этому отчёту (FR-REP-04)."""
    verdict: str                                      # confirm | reject
    corrected_part_id: uuid.UUID | None = None
    at: datetime


class FeedbackRequest(BaseModel):
    """Подтверждение или отклонение результата (FR-REP-04, B3)."""
    verdict: str = Field(pattern="^(confirm|reject)$")
    # При отклонении можно сразу указать правильную деталь
    correct_part_id: uuid.UUID | None = None
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    scan_id: uuid.UUID
    recognition_status: RecognitionStatus
    verdict: str
    part: PartBrief | None = None
    training_sample_created: bool = False
    moderation_task_created: bool = False
    message: str
