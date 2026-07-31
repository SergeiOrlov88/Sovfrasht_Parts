# -*- coding: utf-8 -*-
"""Сканы и распознавание (docs/08 §4; A1 — приём фото, A2 — запуск конвейера)."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.rbac import get_current_user, require_roles
from app.models.enums import Role, ScanStatus
from app.models.org import User, Vessel
from app.models.scan import Recognition, Scan
from app.schemas.scan import (
    RecognitionRead,
    ScanAccepted,
    ScanCreateMeta,
    ScanRead,
    ScanReport,
)
from app.services import scan_service

router = APIRouter(tags=["scans"])

_capture_roles = require_roles(Role.mechanic, Role.supplier_manager)


def _enqueue(scan_id: uuid.UUID) -> None:
    """Ставит скан в очередь распознавания.

    Импорт внутри функции: API не должен падать на старте, если брокер недоступен —
    приём фото важнее, скан не потеряется (NFR-REL-02).
    """
    try:
        from worker.tasks.recognition import process_scan
        process_scan.delay(str(scan_id))
    except Exception:                                  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "Не удалось поставить скан %s в очередь; останется в queued", scan_id
        )


@router.post("/scans", response_model=ScanAccepted, status_code=status.HTTP_202_ACCEPTED,
             summary="Создать скан и запустить распознавание")
async def create_scan(
    photos: list[UploadFile] = File(..., description="от 1 до 3 файлов"),
    meta: str = Form(..., description='JSON: {"vessel_id","geo?","client_scan_id?"}'),
    kinds: str | None = Form(None, description="через запятую: overview,nameplate,context"),
    user: User = Depends(_capture_roles),
    db: AsyncSession = Depends(get_db),
) -> ScanAccepted:
    try:
        payload = ScanCreateMeta.model_validate(json.loads(meta))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AppError(422, "validation_error", "Некорректная часть meta", {"reason": str(exc)[:300]})

    # Идемпотентность: повторная отправка тем же ключом возвращает существующий
    # скан и НЕ запускает распознавание повторно (NFR-REL-04, NFR-COST-01)
    existing = await scan_service.find_by_client_key(db, user.id, payload.client_scan_id)
    if existing is not None:
        return ScanAccepted(scan_id=existing.id, status=ScanStatus(existing.status),
                            idempotent_reuse=True)

    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    scan = await scan_service.create_scan(db, user, payload, photos, kind_list)
    _enqueue(scan.id)
    return ScanAccepted(scan_id=scan.id, status=ScanStatus(scan.status))


async def _get_scan_for_user(db: AsyncSession, user: User, scan_id: uuid.UUID) -> Scan:
    """Скан виден автору и ролям своей организации (docs/08 §4)."""
    scan = await db.scalar(
        select(Scan).options(selectinload(Scan.photos)).where(Scan.id == scan_id)
    )
    if scan is None:
        raise AppError(404, "not_found", "Скан не найден")

    vessel = await db.scalar(select(Vessel).where(Vessel.id == scan.vessel_id))
    if vessel is None or vessel.organization_id != user.organization_id:
        raise AppError(404, "not_found", "Скан не найден")
    # Механик видит только свои сканы; остальные роли — все сканы организации
    if user.role == Role.mechanic.value and scan.author_id != user.id:
        raise AppError(404, "not_found", "Скан не найден")
    return scan


@router.get("/scans/{scan_id}", response_model=ScanRead, summary="Статус и фото скана")
async def get_scan(scan_id: uuid.UUID, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)) -> ScanRead:
    scan = await _get_scan_for_user(db, user, scan_id)
    return ScanRead(
        id=scan.id, vessel_id=scan.vessel_id, author_id=scan.author_id,
        status=ScanStatus(scan.status), created_at=scan.created_at,
        photos=await scan_service.with_signed_urls(scan.photos),
    )


_STATUS_MESSAGE = {
    ScanStatus.queued: "Скан принят и ожидает обработки.",
    ScanStatus.processing: "Распознавание выполняется.",
    ScanStatus.needs_review: "Результат ниже порога достоверности — отправлен эксперту.",
    ScanStatus.error: "Распознавание не удалось. Скан можно отправить на повторную обработку.",
}


@router.get("/scans/{scan_id}/report", response_model=ScanReport, summary="Отчёт по скану")
async def get_report(scan_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> ScanReport:
    scan = await _get_scan_for_user(db, user, scan_id)
    recognition = await db.scalar(select(Recognition).where(Recognition.scan_id == scan.id))
    scan_status = ScanStatus(scan.status)

    below_threshold = bool(
        recognition and (recognition.confidence or 0) < settings.confidence_threshold
    )
    return ScanReport(
        scan_id=scan.id,
        status=scan_status,
        created_at=scan.created_at,
        recognition=RecognitionRead.model_validate(recognition) if recognition else None,
        photos=await scan_service.with_signed_urls(scan.photos),
        needs_expert=scan_status is ScanStatus.needs_review or below_threshold,
        message=_STATUS_MESSAGE.get(scan_status),
    )


@router.post("/scans/{scan_id}/retry", response_model=ScanAccepted,
             status_code=status.HTTP_202_ACCEPTED,
             summary="Переобработать скан после сбоя")
async def retry_scan(scan_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> ScanAccepted:
    """Ни один принятый скан не теряется: после сбоя его можно переобработать
    (NFR-REL-02). Успешный скан переобрабатывать незачем — это лишние деньги."""
    scan = await _get_scan_for_user(db, user, scan_id)
    if scan.status not in {ScanStatus.error.value, ScanStatus.queued.value}:
        raise AppError(409, "conflict",
                       "Переобработка доступна только для сканов со статусом error или queued",
                       {"current_status": scan.status})

    scan.status = ScanStatus.queued.value
    await db.commit()
    _enqueue(scan.id)
    return ScanAccepted(scan_id=scan.id, status=ScanStatus.queued)
