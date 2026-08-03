# -*- coding: utf-8 -*-
"""Схемы панели эксперта (F2) и уведомлений, docs/08 §8-9."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ModerationResolution, ModerationStatus
from app.schemas.scan import CandidateRead, PartBrief, PhotoRead, RecognitionRead


class SlaRead(BaseModel):
    """Время жизни задачи (FR-HITL-04)."""
    wait_seconds: int | None = None      # от создания до взятия в работу
    work_seconds: int | None = None      # от взятия в работу до решения
    total_seconds: int | None = None     # полное время — это и есть SLA


class ModerationTaskRead(BaseModel):
    """Задача в очереди: всё, что нужно эксперту для решения (FR-HITL-02)."""
    id: uuid.UUID
    status: ModerationStatus
    resolution: ModerationResolution | None = None
    expert_id: uuid.UUID | None = None
    created_at: datetime
    claimed_at: datetime | None = None
    resolved_at: datetime | None = None
    sla: SlaRead = Field(default_factory=SlaRead)

    scan_id: uuid.UUID
    vessel_name: str | None = None
    author_name: str | None = None

    recognition: RecognitionRead | None = None
    part: PartBrief | None = None                        # предложенный результат
    candidates: list[CandidateRead] = Field(default_factory=list)
    photos: list[PhotoRead] = Field(default_factory=list)


class ModerationTaskPage(BaseModel):
    items: list[ModerationTaskRead]
    total: int
    page: int
    page_size: int


class ResolveRequest(BaseModel):
    resolution: ModerationResolution
    # Обязателен при corrected; при confirmed уточняет позицию, если её не было
    correct_part_id: uuid.UUID | None = None
    comment: str | None = Field(default=None, max_length=2000)


# ── Уведомления (FR-NOT-01) ──────────────────────────────────────────────────

class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    title: str
    body: str | None = None
    payload: dict | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationRead]
    total: int
    unread: int
    page: int
    page_size: int
