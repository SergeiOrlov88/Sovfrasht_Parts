# -*- coding: utf-8 -*-
"""Закупка: предложения поставщиков (C1) и заявки на снабжение (C2).

Контракты — docs/08 §5. Все предложения идут через адаптер поставщика (ADR-05):
сейчас курируемый список, позже рядом встанет API производителя.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.suppliers.base import SupplierUnavailable
from app.core.database import get_db
from app.core.errors import AppError
from app.core.rbac import get_current_user, require_roles
from app.models.catalog import Part
from app.models.enums import RequestStatus, Role
from app.models.org import User, Vessel
from app.models.scan import PartRequest
from app.schemas.purchase import (
    OfferRead,
    PartOffers,
    PartRequestCreate,
    PartRequestPage,
    PartRequestRead,
    PartRequestStatusUpdate,
    SupplierRead,
    AlternativeOffers,
)
from app.schemas.scan import PartBrief
from app.services import purchase_service

router = APIRouter(tags=["purchase"])

# Оформлять заявки может тот же круг, что и снимать сканы, плюс руководство
_request_roles = require_roles(Role.mechanic, Role.supplier_manager, Role.fleet_owner)
# Двигать заявку по маршруту — снабженец и руководство
_manage_roles = require_roles(Role.supplier_manager, Role.fleet_owner, Role.admin)


def _to_offer(offer) -> OfferRead:
    return OfferRead(
        supplier=SupplierRead(name=offer.supplier.name, type=offer.supplier.type,
                              url=offer.supplier.url, region=offer.supplier.region),
        price=offer.price, lead_time=offer.lead_time, stock_status=offer.stock_status,
        deep_link=offer.deep_link, source=offer.source, fetched_at=offer.fetched_at,
    )


@router.get("/parts/{part_id}/offers", response_model=PartOffers,
            summary="Предложения поставщиков по детали")
async def get_offers(
    part_id: uuid.UUID,
    with_alternatives: bool = Query(True, description="показывать предложения по аналогам"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartOffers:
    part = await db.scalar(select(Part).where(Part.id == part_id))
    if part is None:
        raise AppError(404, "not_found", "Деталь не найдена в каталоге")

    try:
        if with_alternatives:
            own, alternatives = await purchase_service.offers_with_alternatives(db, part)
        else:
            own, alternatives = await purchase_service.offers_for_part(db, part), []
    except SupplierUnavailable as exc:
        # Вкладка «Закупка» не должна ронять отчёт целиком (NFR-REL-03)
        return PartOffers(part=PartBrief.model_validate(part), offers=[], alternatives=[],
                          message=f"Предложения временно недоступны: {exc}")

    return PartOffers(
        part=PartBrief.model_validate(part),
        offers=[_to_offer(o) for o in own],
        alternatives=[
            AlternativeOffers(part=PartBrief.model_validate(alt_part),
                              compatibility=compatibility,
                              offers=[_to_offer(o) for o in alt_offers])
            for alt_part, compatibility, alt_offers in alternatives
        ],
        message=None if own or alternatives else "Предложений по этой детали пока нет.",
    )


@router.post("/part-requests", response_model=PartRequestRead,
             status_code=status.HTTP_201_CREATED, summary="Создать заявку на снабжение")
async def create_request(
    payload: PartRequestCreate,
    user: User = Depends(_request_roles),
    db: AsyncSession = Depends(get_db),
) -> PartRequestRead:
    request, reused = await purchase_service.create_request(
        db, user,
        part_id=payload.part_id, vessel_id=payload.vessel_id,
        quantity=payload.quantity, priority=payload.priority.value,
        comment=payload.comment, recognition_id=payload.recognition_id,
        client_request_id=payload.client_request_id,
    )
    result = await _enrich(db, request)
    result.idempotent_reuse = reused
    return result


async def _enrich(db: AsyncSession, request: PartRequest) -> PartRequestRead:
    part = await db.scalar(select(Part).where(Part.id == request.part_id))
    vessel = await db.scalar(select(Vessel).where(Vessel.id == request.vessel_id))
    return PartRequestRead(
        id=request.id,
        part=PartBrief.model_validate(part) if part else None,
        vessel_id=request.vessel_id,
        vessel_name=vessel.name if vessel else None,
        author_id=request.author_id,
        recognition_id=request.recognition_id,
        quantity=request.quantity,
        priority=request.priority,
        status=request.status,
        comment=request.comment,
        created_at=request.created_at,
        next_statuses=sorted(purchase_service.STATUS_FLOW.get(request.status, set())),
    )


@router.get("/part-requests", response_model=PartRequestPage, summary="Реестр заявок")
async def list_requests(
    status_filter: RequestStatus | None = Query(None, alias="status"),
    vessel_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartRequestPage:
    rows, total = await purchase_service.list_requests(
        db, user, status=status_filter.value if status_filter else None,
        vessel_id=vessel_id, page=page, page_size=page_size,
    )
    return PartRequestPage(items=[await _enrich(db, r) for r in rows],
                           total=total, page=page, page_size=page_size)


@router.get("/part-requests/{request_id}", response_model=PartRequestRead, summary="Заявка")
async def get_request(request_id: uuid.UUID, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> PartRequestRead:
    request = await _get_for_user(db, user, request_id)
    return await _enrich(db, request)


@router.patch("/part-requests/{request_id}", response_model=PartRequestRead,
              summary="Перевести заявку в следующий статус")
async def update_status(
    request_id: uuid.UUID,
    payload: PartRequestStatusUpdate,
    user: User = Depends(_manage_roles),
    db: AsyncSession = Depends(get_db),
) -> PartRequestRead:
    request = await _get_for_user(db, user, request_id)
    request = await purchase_service.change_status(db, request, payload.status.value)
    return await _enrich(db, request)


async def _get_for_user(db: AsyncSession, user: User, request_id: uuid.UUID) -> PartRequest:
    """Заявка видна в пределах организации; механику — только своя (NFR-SEC-03)."""
    request = await db.scalar(select(PartRequest).where(PartRequest.id == request_id))
    if request is None:
        raise AppError(404, "not_found", "Заявка не найдена")
    vessel = await db.scalar(select(Vessel).where(Vessel.id == request.vessel_id))
    if vessel is None or vessel.organization_id != user.organization_id:
        raise AppError(404, "not_found", "Заявка не найдена")
    if user.role == Role.mechanic.value and request.author_id != user.id:
        raise AppError(404, "not_found", "Заявка не найдена")
    return request
