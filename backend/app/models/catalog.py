# -*- coding: utf-8 -*-
"""Каталог: деталь, аналоги, поставщики, предложения, ремонтопригодность (docs/07)."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import JSONType, TZDateTime, TimestampMixin, UUIDPKMixin


class Part(Base, UUIDPKMixin, TimestampMixin):
    """Позиция каталога. Хотя бы один идентификатор обязателен (docs/07 §3)."""
    __tablename__ = "parts"
    __table_args__ = (
        # Жёсткое «минимум один код» снято на шаге 3: часть позиций (крупные
        # судовые дизели) поставляется без публичных номеров. Взамен — мягкий
        # инвариант: у позиции есть название И хотя бы производитель или
        # применимое оборудование, иначе её нечем опознать (docs/07 §3).
        sa.CheckConstraint(
            "name IS NOT NULL AND (maker IS NOT NULL OR equipment IS NOT NULL)",
            name="ck_parts_identifiable",
        ),
        sa.Index("ix_parts_impa_code", "impa_code"),
        sa.Index("ix_parts_issa_code", "issa_code"),
        sa.Index("ix_parts_oem_number", "oem_number"),
        sa.Index("ix_parts_category", "category"),
        sa.Index("ix_parts_maker_norm", "maker_norm"),
        # Нормализованные коды — рабочие ключи точного матчинга (A3)
        sa.Index("ix_parts_impa_norm", "impa_code_norm"),
        sa.Index("ix_parts_issa_norm", "issa_code_norm"),
        sa.Index("ix_parts_oem_norm", "oem_number_norm"),
    )

    impa_code: Mapped[str | None] = mapped_column(sa.String(64))
    issa_code: Mapped[str | None] = mapped_column(sa.String(64))
    oem_number: Mapped[str | None] = mapped_column(sa.String(128))
    maker: Mapped[str | None] = mapped_column(sa.String(255))
    name: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    category: Mapped[str | None] = mapped_column(sa.String(128))
    specs: Mapped[dict | None] = mapped_column(JSONType)
    equipment: Mapped[str | None] = mapped_column(sa.String(512))  # применимое оборудование

    # Канонические формы кодов: верхний регистр, только A-Z0-9. Заполняются
    # одинаково при импорте каталога и при поиске по строке из OCR — иначе
    # «точное совпадение» промахивается на пробелах и дефисах.
    impa_code_norm: Mapped[str | None] = mapped_column(sa.String(64))
    issa_code_norm: Mapped[str | None] = mapped_column(sa.String(64))
    oem_number_norm: Mapped[str | None] = mapped_column(sa.String(128))
    maker_norm: Mapped[str | None] = mapped_column(sa.String(255))

    # ЗАДЕЛ НА ШАГ 3: колонка embedding vector(N) добавляется отдельной миграцией,
    # когда будет выбрана модель эмбеддингов (размерность зависит от неё) — FR-CAT-02.

    aliases: Mapped[list["PartAlias"]] = relationship(
        back_populates="part", cascade="all, delete-orphan", lazy="selectin"
    )
    alternatives: Mapped[list["PartAlternative"]] = relationship(
        back_populates="part", foreign_keys="PartAlternative.part_id"
    )
    offers: Mapped[list["SupplierOffer"]] = relationship(back_populates="part")
    repair_info: Mapped["RepairInfo | None"] = relationship(back_populates="part", uselist=False)


class PartAlias(Base, UUIDPKMixin, TimestampMixin):
    """Альтернативное написание номера или наименования детали.

    Поставщики и каталоги пишут один и тот же номер по-разному; алиас ищется
    точно, наравне с основным номером, — это дешевле и надёжнее нечёткого поиска.
    """
    __tablename__ = "part_aliases"
    __table_args__ = (
        sa.UniqueConstraint("part_id", "alias_norm", name="uq_part_aliases_part_alias"),
        sa.Index("ix_part_aliases_alias_norm", "alias_norm"),
    )

    part_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    alias_norm: Mapped[str] = mapped_column(sa.String(512), nullable=False)

    part: Mapped["Part"] = relationship(back_populates="aliases")


class PartAlternative(Base, UUIDPKMixin, TimestampMixin):
    """Связь «деталь ↔ аналог» с признаком совместимости."""
    __tablename__ = "part_alternatives"
    __table_args__ = (
        sa.UniqueConstraint("part_id", "alt_part_id", name="uq_part_alternatives_pair"),
        sa.CheckConstraint("part_id <> alt_part_id", name="ck_part_alternatives_not_self"),
        sa.CheckConstraint(
            "compatibility IN ('full','partial','kit')", name="ck_part_alternatives_compat"
        ),
        sa.Index("ix_part_alternatives_part_id", "part_id"),
    )

    part_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False
    )
    alt_part_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False
    )
    compatibility: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(sa.Text)

    part: Mapped["Part"] = relationship(back_populates="alternatives", foreign_keys=[part_id])


class Supplier(Base, UUIDPKMixin, TimestampMixin):
    """Поставщик / площадка / OEM."""
    __tablename__ = "suppliers"
    __table_args__ = (
        sa.CheckConstraint(
            "type IN ('marketplace','supplier','oem','reman')", name="ck_suppliers_type"
        ),
    )

    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    url: Mapped[str | None] = mapped_column(sa.String(1024))
    region: Mapped[str | None] = mapped_column(sa.String(128))

    offers: Mapped[list["SupplierOffer"]] = relationship(back_populates="supplier")


class SupplierOffer(Base, UUIDPKMixin, TimestampMixin):
    """Предложение поставщика по детали. На MVP цены справочные/курируемые."""
    __tablename__ = "supplier_offers"
    __table_args__ = (
        sa.CheckConstraint("stock_status IN ('in','low','out')", name="ck_supplier_offers_stock"),
        sa.CheckConstraint("source IN ('curated','demo','api')", name="ck_supplier_offers_source"),
        sa.UniqueConstraint("part_id", "supplier_id", name="uq_supplier_offers_part_supplier"),
        sa.Index("ix_supplier_offers_part_id", "part_id"),
        sa.Index("ix_supplier_offers_supplier_id", "supplier_id"),
    )

    part_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[str | None] = mapped_column(sa.String(64))
    lead_time: Mapped[str | None] = mapped_column(sa.String(128))
    stock_status: Mapped[str | None] = mapped_column(sa.String(16))
    deep_link: Mapped[str | None] = mapped_column(sa.String(2048))
    # Откуда предложение: курируемый список / демо-данные / внешний API.
    # Нужен, чтобы отличать демонстрационные цены от полученных по API (ADR-05).
    source: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="curated")
    fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    part: Mapped["Part"] = relationship(back_populates="offers")
    supplier: Mapped["Supplier"] = relationship(back_populates="offers")


class RepairInfo(Base, UUIDPKMixin, TimestampMixin):
    """Ремонтопригодность детали (D1)."""
    __tablename__ = "repair_infos"
    __table_args__ = (
        sa.UniqueConstraint("part_id", name="uq_repair_infos_part"),
        sa.CheckConstraint("verdict IN ('repair','replace')", name="ck_repair_infos_verdict"),
    )

    part_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False
    )
    verdict: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    rationale: Mapped[str | None] = mapped_column(sa.Text)
    repair_cost_estimate: Mapped[str | None] = mapped_column(sa.String(64))
    replace_cost_estimate: Mapped[str | None] = mapped_column(sa.String(64))
    repair_time: Mapped[str | None] = mapped_column(sa.String(64))

    part: Mapped["Part"] = relationship(back_populates="repair_info")
