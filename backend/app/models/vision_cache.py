# -*- coding: utf-8 -*-
"""Кэш ответов платных vision/OCR API (NFR-COST-01).

Ключ — пара «провайдер + sha256 изображения»: одно и то же фото не оплачивается
дважды, даже если его прислали в разных сканах или после переобработки.
"""
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import JSONType, CreatedAtMixin, UUIDPKMixin


class VisionCache(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "vision_cache"
    __table_args__ = (
        sa.UniqueConstraint("provider", "image_sha256", name="uq_vision_cache_provider_image"),
        sa.Index("ix_vision_cache_created_at", "created_at"),
    )

    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    image_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(sa.String(128))
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    # Счётчик попаданий — по нему видно, сколько запросов к платному API сэкономлено
    hit_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
