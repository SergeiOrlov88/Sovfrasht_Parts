# -*- coding: utf-8 -*-
"""Закупка: предложения поставщиков (C1) и заявки на снабжение (C2)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.suppliers.base import Offer, SupplierProvider, SupplierUnavailable
from app.adapters.suppliers.registry import get_supplier_provider
from app.core.config import settings
from app.core.errors import AppError
from app.models.catalog import Part, PartAlternative
from app.models.enums import RequestStatus
from app.models.org import User, Vessel
from app.models.scan import PartRequest, Recognition, Scan

# Разрешённые переходы статусов заявки (FR-PRO-04).
# Замкнутых веток нет: rejected и received — конечные.
STATUS_FLOW: dict[str, set[str]] = {
    RequestStatus.new.value: {RequestStatus.in_review.value, RequestStatus.rejected.value},
    RequestStatus.in_review.value: {RequestStatus.approved.value, RequestStatus.rejected.value},
    RequestStatus.approved.value: {RequestStatus.ordered.value, RequestStatus.rejected.value},
    RequestStatus.ordered.value: {RequestStatus.received.value},
    RequestStatus.rejected.value: set(),
    RequestStatus.received.value: set(),
}


async def offers_for_part(db: AsyncSession, part: Part,
                          provider: SupplierProvider | None = None) -> list[Offer]:
    """Предложения по детали (FR-PRO-01/02) через адаптер поставщика."""
    provider = provider or get_supplier_provider(db)
    return await provider.get_offers(part)


async def offers_with_alternatives(db: AsyncSession, part: Part) -> tuple[list[Offer], list[tuple[Part, str, list[Offer]]]]:
    """Предложения по самой детали и по её аналогам (FR-PRO-02, FR-REP-03).

    Аналог с наличием на складе часто выгоднее оригинала «под заказ» — поэтому
    его предложения показываем рядом, а не прячем.
    """
    provider = get_supplier_provider(db)
    own = await provider.get_offers(part)

    rows = (await db.execute(
        select(PartAlternative, Part)
        .join(Part, Part.id == PartAlternative.alt_part_id)
        .where(PartAlternative.part_id == part.id)
    )).all()

    alternatives: list[tuple[Part, str, list[Offer]]] = []
    for link, alt_part in rows:
        alt_offers = await provider.get_offers(alt_part)
        alternatives.append((alt_part, link.compatibility, alt_offers))
    return own, alternatives


# ── Заявки (C2) ──────────────────────────────────────────────────────────────

async def _assert_vessel_access(db: AsyncSession, user: User, vessel_id: uuid.UUID) -> Vessel:
    vessel = await db.scalar(select(Vessel).where(Vessel.id == vessel_id))
    if vessel is None or vessel.organization_id != user.organization_id:
        raise AppError(404, "not_found", "Судно не найдено")
    if user.role == "mechanic" and vessel.id not in {v.id for v in user.vessels}:
        raise AppError(404, "not_found", "Судно не найдено")
    return vessel


async def find_by_client_key(db: AsyncSession, author_id: uuid.UUID,
                             client_request_id: str | None) -> PartRequest | None:
    """Идемпотентность заявки (NFR-REL-04): тот же ключ — та же заявка."""
    if not client_request_id:
        return None
    return await db.scalar(select(PartRequest).where(
        PartRequest.author_id == author_id,
        PartRequest.client_request_id == client_request_id,
    ))


async def create_request(db: AsyncSession, user: User, *, part_id: uuid.UUID,
                         vessel_id: uuid.UUID, quantity: int, priority: str,
                         comment: str | None, recognition_id: uuid.UUID | None,
                         client_request_id: str | None) -> tuple[PartRequest, bool]:
    """Создаёт заявку. Возвращает (заявка, было_ли_переиспользование)."""
    existing = await find_by_client_key(db, user.id, client_request_id)
    if existing is not None:
        return existing, True

    await _assert_vessel_access(db, user, vessel_id)

    part = await db.scalar(select(Part).where(Part.id == part_id))
    if part is None:
        raise AppError(404, "not_found", "Деталь не найдена в каталоге")

    # Ниже порога достоверности заявка автоматически не оформляется:
    # нужен подтверждённый или исправленный человеком результат
    # (FR-REC-04, NFR-ACC-03).
    if recognition_id is not None:
        recognition = await db.scalar(
            select(Recognition).where(Recognition.id == recognition_id)
        )
        if recognition is None:
            raise AppError(404, "not_found", "Результат распознавания не найден")

        scan = await db.scalar(select(Scan).where(Scan.id == recognition.scan_id))
        if scan is None or scan.author_id != user.id and user.role == "mechanic":
            raise AppError(404, "not_found", "Результат распознавания не найден")

        confirmed = recognition.status in {"confirmed", "corrected"}
        if (recognition.confidence or 0) < settings.confidence_threshold and not confirmed:
            raise AppError(
                422, "confidence_too_low",
                f"Достоверность {recognition.confidence or 0}% ниже порога "
                f"{settings.confidence_threshold}%. Подтвердите результат или "
                f"отправьте эксперту — заявка пока не оформляется.",
                {"confidence": recognition.confidence or 0,
                 "threshold": settings.confidence_threshold},
            )

    request = PartRequest(
        recognition_id=recognition_id,
        part_id=part_id,
        vessel_id=vessel_id,
        author_id=user.id,
        client_request_id=client_request_id,
        quantity=quantity,
        priority=priority,
        status=RequestStatus.new.value,
        comment=comment,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    return request, False


async def change_status(db: AsyncSession, request: PartRequest, new_status: str) -> PartRequest:
    """Перевод заявки по маршруту new→in_review→approved/rejected→ordered→received."""
    allowed = STATUS_FLOW.get(request.status, set())
    if new_status not in allowed:
        raise AppError(
            409, "invalid_transition",
            f"Из статуса «{request.status}» нельзя перейти в «{new_status}»",
            {"current": request.status, "allowed": sorted(allowed)},
        )
    request.status = new_status
    await db.commit()
    await db.refresh(request)
    return request


async def list_requests(db: AsyncSession, user: User, *, status: str | None,
                        vessel_id: uuid.UUID | None, page: int, page_size: int):
    """Реестр заявок организации (FR-PRO-04)."""
    base = (select(PartRequest)
            .join(Vessel, Vessel.id == PartRequest.vessel_id)
            .where(Vessel.organization_id == user.organization_id))
    # Механик видит только свои заявки; снабженец и руководство — все по организации
    if user.role == "mechanic":
        base = base.where(PartRequest.author_id == user.id)
    if status:
        base = base.where(PartRequest.status == status)
    if vessel_id:
        base = base.where(PartRequest.vessel_id == vessel_id)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(
        base.order_by(PartRequest.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    return list(rows), total
