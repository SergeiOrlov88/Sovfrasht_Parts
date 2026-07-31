# -*- coding: utf-8 -*-
"""Суда организации (docs/08 §3). Роли: admin, fleet_owner."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.rbac import require_roles
from app.models.enums import Role
from app.models.org import User, Vessel
from app.schemas.admin import VesselCreate, VesselPage, VesselRead, VesselUpdate

router = APIRouter(tags=["vessels"])

_manage = require_roles(Role.admin, Role.fleet_owner)


@router.get("/vessels", response_model=VesselPage, summary="Суда организации")
async def list_vessels(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> VesselPage:
    base = select(Vessel).where(Vessel.organization_id == user.organization_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(
        base.order_by(Vessel.name).offset((page - 1) * page_size).limit(page_size)
    )).all()
    return VesselPage(items=[VesselRead.model_validate(v) for v in rows],
                      total=total, page=page, page_size=page_size)


@router.post("/vessels", response_model=VesselRead, status_code=201, summary="Добавить судно")
async def create_vessel(
    payload: VesselCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> VesselRead:
    if payload.imo:
        dup = await db.scalar(select(Vessel).where(
            Vessel.organization_id == user.organization_id, Vessel.imo == payload.imo
        ))
        if dup:
            raise AppError(409, "conflict", "Судно с таким IMO уже есть в организации")

    vessel = Vessel(organization_id=user.organization_id, name=payload.name,
                    imo=payload.imo, type=payload.type)
    db.add(vessel)
    await db.commit()
    await db.refresh(vessel)
    return VesselRead.model_validate(vessel)


@router.patch("/vessels/{vessel_id}", response_model=VesselRead, summary="Изменить судно")
async def update_vessel(
    vessel_id: uuid.UUID,
    payload: VesselUpdate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> VesselRead:
    vessel = await db.scalar(select(Vessel).where(Vessel.id == vessel_id))
    if vessel is None or vessel.organization_id != user.organization_id:
        raise AppError(404, "not_found", "Судно не найдено")

    if payload.name is not None:
        vessel.name = payload.name
    if payload.imo is not None:
        vessel.imo = payload.imo
    if payload.type is not None:
        vessel.type = payload.type

    await db.commit()
    await db.refresh(vessel)
    return VesselRead.model_validate(vessel)
