# -*- coding: utf-8 -*-
"""Уведомления внутри приложения (FR-NOT-01).

Канал MVP — только in-app: запись создаётся в БД и показывается пользователю.
Email и пуш — следующий этап, для них здесь же появится статус доставки.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import JSONType, CreatedAtMixin, TZDateTime, UUIDPKMixin


class Notification(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        sa.Index("ix_notifications_user_id", "user_id"),
        sa.Index("ix_notifications_read_at", "read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Тип события: expert_resolved | scan_done | request_status ...
    type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(sa.Text)
    # Куда вести пользователя: {"scan_id": "...", "part_id": "..."}
    payload: Mapped[dict | None] = mapped_column(JSONType)
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime)
