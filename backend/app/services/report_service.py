# -*- coding: utf-8 -*-
"""Сборка отчёта (B1, FR-REP-01..03) и обратная связь (B3, FR-REP-04)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.models.catalog import Part, PartAlternative
from app.models.enums import (
    ModerationResolution,
    ModerationStatus,
    RecognitionStatus,
    ScanStatus,
    TrainingSampleSource,
)
from app.models.scan import (
    ModerationTask,
    Photo,
    Recognition,
    RecognitionCandidate,
    Scan,
    TrainingSample,
)

# Градация индикатора достоверности (FR-REP-02). Границы вокруг порога:
# «high» — заметно выше порога, «medium» — около него, «low» — ниже.
_HIGH_MARGIN = 15


def confidence_level(confidence: int | None) -> str:
    if confidence is None:
        return "low"
    if confidence >= settings.confidence_threshold + _HIGH_MARGIN:
        return "high"
    if confidence >= settings.confidence_threshold:
        return "medium"
    return "low"


def build_warning(confidence: int | None, catalog_status: str | None) -> str | None:
    """Предупреждение под индикатором достоверности (FR-REP-02)."""
    if catalog_status == "not_found":
        return ("Детали нет в каталоге — коды подобрать не удалось. "
                "Оформлять заявку по этому результату нельзя, отправьте эксперту.")
    if confidence is None or confidence < settings.confidence_threshold:
        return (f"Достоверность {confidence or 0}% ниже порога "
                f"{settings.confidence_threshold}%. Результат требует подтверждения — "
                f"проверьте кандидатов или отправьте эксперту.")
    if catalog_status == "candidates":
        return "Точного совпадения нет — проверьте, верно ли выбрана позиция из списка."
    return None


async def load_alternatives(db: AsyncSession, part_id: uuid.UUID | None) -> list[tuple[Part, str, str | None]]:
    """Аналоги/заменители детали (FR-REP-03, FR-CAT-04)."""
    if part_id is None:
        return []
    rows = (await db.execute(
        select(PartAlternative, Part)
        .join(Part, Part.id == PartAlternative.alt_part_id)
        .where(PartAlternative.part_id == part_id)
    )).all()
    return [(part, alt.compatibility, alt.note) for alt, part in rows]


async def _nameplate_photo_id(db: AsyncSession, scan_id: uuid.UUID) -> uuid.UUID | None:
    """Для обучающего примера предпочитаем кадр шильдика."""
    photos = list((await db.scalars(select(Photo).where(Photo.scan_id == scan_id))).all())
    if not photos:
        return None
    for photo in photos:
        if photo.kind == "nameplate":
            return photo.id
    return photos[0].id


async def submit_feedback(db: AsyncSession, scan: Scan, user_id: uuid.UUID,
                          verdict: str, correct_part_id: uuid.UUID | None,
                          comment: str | None) -> dict:
    """Подтверждение или исправление результата (FR-REP-04).

    Подтверждённые и исправленные результаты складываются в TrainingSample —
    датасет для дообучения (FR-REC-06). Отклонение без указания правильной
    детали создаёт задачу эксперту: пользователь сказал «не то», но что именно
    верно — знает не он (F1).
    """
    recognition = await db.scalar(select(Recognition).where(Recognition.scan_id == scan.id))
    if recognition is None:
        raise AppError(409, "conflict",
                       "По этому скану ещё нет результата распознавания",
                       {"scan_status": scan.status})

    corrected_part: Part | None = None
    if correct_part_id is not None:
        corrected_part = await db.scalar(select(Part).where(Part.id == correct_part_id))
        if corrected_part is None:
            raise AppError(404, "not_found", "Указанная деталь не найдена в каталоге")

    moderation_created = False
    training_created = False

    if verdict == "confirm":
        if recognition.part_id is None and corrected_part is None:
            raise AppError(
                422, "validation_error",
                "Подтверждать нечего: деталь не определена. "
                "Укажите правильную позицию или отправьте эксперту.")
        if corrected_part is not None:
            recognition.part_id = corrected_part.id
            recognition.status = RecognitionStatus.corrected.value
        else:
            recognition.status = RecognitionStatus.confirmed.value
        scan.status = ScanStatus.done.value
        message = "Результат подтверждён."
    else:                                              # reject
        if corrected_part is not None:
            # Пользователь сам указал верную деталь — это самый ценный сигнал
            recognition.part_id = corrected_part.id
            recognition.status = RecognitionStatus.corrected.value
            scan.status = ScanStatus.done.value
            message = "Спасибо, результат исправлен."
        else:
            recognition.status = RecognitionStatus.rejected.value
            scan.status = ScanStatus.needs_review.value
            message = "Результат отклонён и передан эксперту."

    await db.flush()

    # Обучающий пример — только когда известна верная деталь (FR-REC-06)
    correct_id = corrected_part.id if corrected_part else (
        recognition.part_id if verdict == "confirm" else None
    )
    if correct_id is not None:
        exists = await db.scalar(select(TrainingSample).where(
            TrainingSample.recognition_id == recognition.id,
            TrainingSample.correct_part_id == correct_id,
        ))
        if exists is None:
            db.add(TrainingSample(
                recognition_id=recognition.id,
                photo_id=await _nameplate_photo_id(db, scan.id),
                correct_part_id=correct_id,
                source=TrainingSampleSource.user_feedback.value,
            ))
            training_created = True

    # Отклонение без правильной детали -> к эксперту (F1)
    if verdict == "reject" and corrected_part is None:
        task = await db.scalar(select(ModerationTask).where(
            ModerationTask.recognition_id == recognition.id,
            ModerationTask.status != ModerationStatus.resolved.value,
        ))
        if task is None:
            db.add(ModerationTask(recognition_id=recognition.id,
                                  status=ModerationStatus.pending.value))
            moderation_created = True

    # Фиксируем ответ пользователя в аудите обратной связи
    recognition.feedback_verdict = verdict
    recognition.feedback_by = user_id
    recognition.feedback_at = datetime.now(timezone.utc)
    recognition.feedback_comment = comment

    await db.commit()
    await db.refresh(recognition)

    return {
        "recognition": recognition,
        "part": corrected_part,
        "training_sample_created": training_created,
        "moderation_task_created": moderation_created,
        "message": message,
    }


async def candidate_parts(db: AsyncSession, recognition_id: uuid.UUID) -> list[tuple[RecognitionCandidate, Part]]:
    rows = (await db.execute(
        select(RecognitionCandidate, Part)
        .join(Part, Part.id == RecognitionCandidate.part_id)
        .where(RecognitionCandidate.recognition_id == recognition_id)
        .order_by(RecognitionCandidate.relevance.desc())
    )).all()
    return [(c, p) for c, p in rows]


def resolution_for(verdict: str, corrected: bool) -> str:
    if verdict == "confirm":
        return ModerationResolution.confirmed.value
    return (ModerationResolution.corrected if corrected else ModerationResolution.rejected).value
