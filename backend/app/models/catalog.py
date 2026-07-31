# -*- coding: utf-8 -*-
"""Каталог: деталь, аналоги, поставщики, предложения, ремонтопригодность (docs/07)."""
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import JSONType, TimestampMixin, UUIDPKMixin


class Part(Base, UUIDPKMixin, TimestampMixin):
    """Позиция каталога. Хотя бы один идентификатор обязателен (docs/07 §3)."""
    __tablename__ = "parts"
    __table_args__ = (
        sa.CheckConstraint(
            "impa_code IS NOT NULL OR issa_code IS NOT NULL OR oem_number IS NOT NULL",
            name="ck_parts_has_identifier",
        ),
        sa.Index("ix_parts_impa_code", "impa_code"),
        sa.Index("ix_parts_issa_code", "issa_code"),
        sa.Index("ix_parts_oem_number", "oem_number"),
        sa.Index("ix_parts_category", "category"),
    )

    impa_code: Mapped[str | None] = mapped_column(sa.String(64))
    issa_code: Mapped[str | None] = mapped_column(sa.String(64))
    oem_number: Mapped[str | None] = mapped_column(sa.String(128))
    maker: Mapped[str | None] = mapped_column(sa.String(255))
    name: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    category: Mapped[str | None] = mapped_column(sa.String(128))
    specs: Mapped[dict | None] = mapped_column(JSONType)
    equipment: Mapped[str | None] = mapped_column(sa.String(512))  # применимое оборудование

    # ЗАДЕЛ НА ШАГ 3: колонка embedding vector(N) добавляется отдельной миграцией,
    # когда будет выбрана модель эмбеддингов (размерность зависит от неё) — FR-CAT-02.

    alternatives: Mapped[list["PartAlternative"]] = relationship(
        back_populates="part", foreign_keys="PartAlternative.part_id"
    )
    offers: Mapped[list["SupplierOffer"]] = relationship(back_populates="part")
    repair_info: Mapped["RepairInfo | None"] = relationship(back_populates="part", uselist=False)


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
            "type IN ('marketplace','supplier','oem')", name="ck_suppliers_type"
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
