# -*- coding: utf-8 -*-
"""Скан, фото, распознавание, кандидаты, модерация, обучающие примеры, заявки (docs/07)."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TZDateTime, TimestampMixin, UUIDPKMixin


class Scan(Base, UUIDPKMixin, TimestampMixin):
    """Единица распознавания: набор фото + метаданные.

    client_scan_id — клиентский ключ идемпотентности (NFR-REL-04): повторная
    отправка с тем же значением обязана вернуть существующий скан, а не создать дубль.
    """
    __tablename__ = "scans"
    __table_args__ = (
        sa.UniqueConstraint("author_id", "client_scan_id", name="uq_scans_author_client_key"),
        sa.CheckConstraint(
            "status IN ('queued','processing','done','needs_review','error')",
            name="ck_scans_status",
        ),
        sa.Index("ix_scans_vessel_id", "vessel_id"),
        sa.Index("ix_scans_author_id", "author_id"),
        sa.Index("ix_scans_status", "status"),
    )

    vessel_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("vessels.id", ondelete="RESTRICT"), nullable=False
    )
    # Автор не удаляется жёстко — историчность (docs/07 §3)
    author_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    client_scan_id: Mapped[str | None] = mapped_column(sa.String(128))
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="queued")
    geo_lat: Mapped[float | None] = mapped_column(sa.Float)
    geo_lon: Mapped[float | None] = mapped_column(sa.Float)

    photos: Mapped[list["Photo"]] = relationship(back_populates="scan", cascade="all, delete-orphan")
    recognition: Mapped["Recognition | None"] = relationship(back_populates="scan", uselist=False)


class Photo(Base, UUIDPKMixin, TimestampMixin):
    """Фото скана. Файл лежит в закрытом хранилище, доступ по подписанной ссылке (NFR-SEC-04)."""
    __tablename__ = "photos"
    __table_args__ = (
        sa.CheckConstraint(
            "kind IN ('overview','nameplate','context')", name="ck_photos_kind"
        ),
        sa.Index("ix_photos_scan_id", "scan_id"),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    width: Mapped[int | None] = mapped_column(sa.Integer)
    height: Mapped[int | None] = mapped_column(sa.Integer)

    scan: Mapped["Scan"] = relationship(back_populates="photos")


class Recognition(Base, UUIDPKMixin, TimestampMixin):
    """Результат распознавания скана. part_id пуст до подтверждения (docs/07 §3)."""
    __tablename__ = "recognitions"
    __table_args__ = (
        sa.UniqueConstraint("scan_id", name="uq_recognitions_scan"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_recognitions_confidence"),
        sa.CheckConstraint(
            "status IN ('auto','confirmed','corrected','rejected')", name="ck_recognitions_status"
        ),
        sa.Index("ix_recognitions_part_id", "part_id"),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    part_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="SET NULL")
    )
    confidence: Mapped[int | None] = mapped_column(sa.Integer)
    ocr_text: Mapped[str | None] = mapped_column(sa.Text)
    maker_detected: Mapped[str | None] = mapped_column(sa.String(255))
    oem_detected: Mapped[str | None] = mapped_column(sa.String(255))
    model_version: Mapped[str | None] = mapped_column(sa.String(128))
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="auto")

    scan: Mapped["Scan"] = relationship(back_populates="recognition")
    candidates: Mapped[list["RecognitionCandidate"]] = relationship(
        back_populates="recognition", cascade="all, delete-orphan"
    )


class RecognitionCandidate(Base, UUIDPKMixin, TimestampMixin):
    """Альтернативный кандидат — минимум один обязателен по NFR-ACC-02."""
    __tablename__ = "recognition_candidates"
    __table_args__ = (
        sa.CheckConstraint("relevance BETWEEN 0 AND 1", name="ck_recognition_candidates_relevance"),
        sa.Index("ix_recognition_candidates_recognition_id", "recognition_id"),
    )

    recognition_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("recognitions.id", ondelete="CASCADE"), nullable=False
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False
    )
    relevance: Mapped[float | None] = mapped_column(sa.Float)

    recognition: Mapped["Recognition"] = relationship(back_populates="candidates")


class PartRequest(Base, UUIDPKMixin, TimestampMixin):
    """Заявка на снабжение из отчёта (C2). Идемпотентна по клиентскому ключу (NFR-REL-04)."""
    __tablename__ = "part_requests"
    __table_args__ = (
        sa.UniqueConstraint("author_id", "client_request_id", name="uq_part_requests_client_key"),
        sa.CheckConstraint("quantity > 0", name="ck_part_requests_quantity"),
        sa.CheckConstraint(
            "priority IN ('low','normal','urgent')", name="ck_part_requests_priority"
        ),
        sa.CheckConstraint(
            "status IN ('new','in_review','approved','rejected','ordered','received')",
            name="ck_part_requests_status",
        ),
        sa.Index("ix_part_requests_vessel_id", "vessel_id"),
        sa.Index("ix_part_requests_status", "status"),
    )

    recognition_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("recognitions.id", ondelete="SET NULL")
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False
    )
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("vessels.id", ondelete="RESTRICT"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    client_request_id: Mapped[str | None] = mapped_column(sa.String(128))
    quantity: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    priority: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="new")
    comment: Mapped[str | None] = mapped_column(sa.Text)


class ModerationTask(Base, UUIDPKMixin, TimestampMixin):
    """Задача HITL (F1, F2): создаётся при confidence ниже порога или вручную."""
    __tablename__ = "moderation_tasks"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('pending','in_progress','resolved')", name="ck_moderation_tasks_status"
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('confirmed','corrected','rejected')",
            name="ck_moderation_tasks_resolution",
        ),
        sa.Index("ix_moderation_tasks_status", "status"),
        sa.Index("ix_moderation_tasks_expert_id", "expert_id"),
    )

    recognition_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("recognitions.id", ondelete="CASCADE"), nullable=False
    )
    expert_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="pending")
    resolution: Mapped[str | None] = mapped_column(sa.String(16))
    corrected_part_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class TrainingSample(Base, UUIDPKMixin, TimestampMixin):
    """Размеченный пример для дообучения (FR-REC-06)."""
    __tablename__ = "training_samples"
    __table_args__ = (
        sa.CheckConstraint(
            "source IN ('user_feedback','expert')", name="ck_training_samples_source"
        ),
        sa.Index("ix_training_samples_recognition_id", "recognition_id"),
    )

    recognition_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("recognitions.id", ondelete="CASCADE"), nullable=False
    )
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("photos.id", ondelete="SET NULL")
    )
    correct_part_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False)
