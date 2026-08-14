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
from app.models.catalog import Part
from app.models.scan import Recognition, Scan
from app.schemas.scan import (
    AlternativeRead,
    CandidateRead,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackState,
    IdentificationRead,
    PartBrief,
    RecognitionRead,
    ScanAccepted,
    ScanCreateMeta,
    ScanRead,
    ScanReport,
)
from app.services import report_service, scan_service

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

# Пояснение про каталог: «нет в каталоге» говорим прямо, а не подсовываем похожее
_CATALOG_MESSAGE = {
    "matched": None,
    "candidates": "Точного совпадения в каталоге нет — показаны близкие позиции.",
    "not_found": "Детали нет в каталоге. Коды подобрать не удалось — нужен эксперт.",
}

# Когда деталь опознана vision-моделью, «не найдено в каталоге» перестаёт быть
# приговором: это лишь значит, что кодов для закупки пока нет. Формулировку
# меняем, иначе пользователь читает содержательный отчёт под сообщением о провале.
_CATALOG_MESSAGE_IDENTIFIED = {
    "matched": None,
    "candidates": "Деталь опознана. Точного совпадения в каталоге нет — показаны близкие позиции.",
    "not_found": "Деталь опознана, но в каталоге закупки её нет: "
                 "кодов и поставщиков пока не подобрать.",
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

    part: Part | None = None
    candidates: list[CandidateRead] = []
    alternatives: list[AlternativeRead] = []
    feedback: FeedbackState | None = None

    if recognition is not None:
        if recognition.part_id:
            part = await db.scalar(select(Part).where(Part.id == recognition.part_id))
        candidates = [
            CandidateRead(part=PartBrief.model_validate(p), relevance=c.relevance or 0.0)
            for c, p in await report_service.candidate_parts(db, recognition.id)
        ]
        # Аналоги/заменители найденной позиции (FR-REP-03)
        alternatives = [
            AlternativeRead(part=PartBrief.model_validate(alt_part),
                            compatibility=compatibility, note=note)
            for alt_part, compatibility, note in
            await report_service.load_alternatives(db, recognition.part_id)
        ]
        if recognition.feedback_verdict and recognition.feedback_at:
            feedback = FeedbackState(verdict=recognition.feedback_verdict,
                                     corrected_part_id=recognition.part_id,
                                     at=recognition.feedback_at)

    identification = report_service.extract_identification(recognition)

    message = _STATUS_MESSAGE.get(scan_status)
    if recognition is not None:
        table = _CATALOG_MESSAGE_IDENTIFIED if identification else _CATALOG_MESSAGE
        message = table.get(recognition.catalog_status or "", message) or message

    confidence = recognition.confidence if recognition else None
    needs_expert = scan_status is ScanStatus.needs_review or below_threshold
    ready = recognition is not None and scan_status in {ScanStatus.done, ScanStatus.needs_review}

    return ScanReport(
        scan_id=scan.id,
        vessel_id=scan.vessel_id,
        status=scan_status,
        created_at=scan.created_at,
        recognition=RecognitionRead.model_validate(recognition) if recognition else None,
        identification=IdentificationRead(**identification) if identification else None,
        part=PartBrief.model_validate(part) if part else None,
        candidates=candidates,
        alternatives=alternatives,
        photos=await scan_service.with_signed_urls(scan.photos),
        needs_expert=needs_expert,
        confidence=confidence,
        confidence_level=report_service.confidence_level(confidence) if recognition else None,
        warning=report_service.build_warning(
            confidence, recognition.catalog_status if recognition else None,
            identified=bool(identification),
        ) if recognition else None,
        # Подтверждать имеет смысл только когда есть что подтверждать
        can_confirm=bool(ready and (part or candidates) and feedback is None),
        can_request_expert=bool(ready and feedback is None),
        feedback=feedback,
        message=message,
    )


@router.post("/scans/{scan_id}/feedback", response_model=FeedbackResponse,
             summary="Подтвердить или исправить результат распознавания")
async def submit_feedback(
    scan_id: uuid.UUID,
    payload: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """Обратная связь по отчёту (FR-REP-04, B3).

    Подтверждение и исправление пополняют датасет TrainingSample (FR-REC-06);
    отклонение без указания верной детали создаёт задачу эксперту (F1).
    """
    scan = await _get_scan_for_user(db, user, scan_id)
    result = await report_service.submit_feedback(
        db, scan, user.id, payload.verdict, payload.correct_part_id, payload.comment
    )
    recognition = result["recognition"]
    part = result["part"]
    if part is None and recognition.part_id:
        part = await db.scalar(select(Part).where(Part.id == recognition.part_id))

    return FeedbackResponse(
        scan_id=scan.id,
        recognition_status=recognition.status,
        verdict=payload.verdict,
        part=PartBrief.model_validate(part) if part else None,
        training_sample_created=result["training_sample_created"],
        moderation_task_created=result["moderation_task_created"],
        message=result["message"],
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
