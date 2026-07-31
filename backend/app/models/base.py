# -*- coding: utf-8 -*-
"""Общие примитивы моделей: типы, миксины.

Типы подобраны диалектно-нейтральными: на PostgreSQL это native uuid/jsonb,
на SQLite (используется в тестах) — совместимые аналоги.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

# jsonb на Postgres, обычный json на прочих диалектах
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# Время храним в UTC (docs/07 §3), отображение в TZ пользователя — на клиенте
TZDateTime = sa.DateTime(timezone=True)


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=sa.func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()
    )
