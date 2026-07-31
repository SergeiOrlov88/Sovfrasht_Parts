# -*- coding: utf-8 -*-
"""Организация, судно, пользователь — основа RBAC (docs/07)."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models import enums
from app.models.base import CreatedAtMixin, TZDateTime, TimestampMixin, UUIDPKMixin


class Organization(Base, UUIDPKMixin, TimestampMixin):
    """Компания. На старте single-tenant — одна организация «Совфрахт»."""
    __tablename__ = "organizations"
    __table_args__ = (
        sa.CheckConstraint(
            "type IN ('owner','shipyard')", name="ck_organizations_type"
        ),
    )

    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=enums.OrganizationType.owner.value
    )

    vessels: Mapped[list["Vessel"]] = relationship(back_populates="organization")
    users: Mapped[list["User"]] = relationship(back_populates="organization")


class Vessel(Base, UUIDPKMixin, TimestampMixin):
    """Судно. IMO уникален в пределах организации."""
    __tablename__ = "vessels"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "imo", name="uq_vessels_org_imo"),
        sa.Index("ix_vessels_organization_id", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    imo: Mapped[str | None] = mapped_column(sa.String(32))
    type: Mapped[str | None] = mapped_column(sa.String(128))

    organization: Mapped["Organization"] = relationship(back_populates="vessels")


# Механик привязан к одному или нескольким судам (FR-AUTH-03)
user_vessels = sa.Table(
    "user_vessels",
    Base.metadata,
    sa.Column("user_id", sa.Uuid(as_uuid=True),
              sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("vessel_id", sa.Uuid(as_uuid=True),
              sa.ForeignKey("vessels.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base, UUIDPKMixin, TimestampMixin):
    """Пользователь с ролью, принадлежит организации (FR-AUTH-02, FR-AUTH-03).

    Удаление — мягкое: сканы и заявки должны сохранять историчность (docs/07 §3).
    """
    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("login", name="uq_users_login"),
        sa.CheckConstraint(
            "role IN ('mechanic','supplier_manager','fleet_owner','expert','admin')",
            name="ck_users_role",
        ),
        sa.Index("ix_users_organization_id", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    login: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime)  # мягкое удаление

    organization: Mapped["Organization"] = relationship(back_populates="users")
    vessels: Mapped[list["Vessel"]] = relationship(secondary=user_vessels, lazy="selectin")
