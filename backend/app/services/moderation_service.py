# -*- coding: utf-8 -*-
"""Панель эксперта: очередь, взятие в работу, решение (F2, FR-HITL-02/03/04)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models.catalog import Part
from app.models.enums import (
    ModerationResolution,
    ModerationStatus,
    RecognitionStatus,
    ScanStatus,
    TrainingSampleSource,
)
from app.models.notification import Notification
from app.models.org import User, Vessel
from app.models.scan import (
    ModerationTask,
    Photo,
    Recognition,
    RecognitionCandidate,
    Scan,
    TrainingSample,
)


@dataclass(slots=True)
class TaskContext:
    """Задача вместе со всем, что эксперту нужно для решения (FR-HITL-02)."""
    task: ModerationTask
    recognition: Recognition
    scan: Scan
    photos: list[Photo]
    part: Part | None
    candidates: list[tuple[RecognitionCandidate, Part]]
    author: User | None
    vessel: Vessel | None


def sla_seconds(task: ModerationTask) -> dict[str, int | None]:
    """SLA-метрика (FR-HITL-04): сколько ждала очереди и сколько заняло решение.

    Считаем на чтении, а не храним: created_at/claimed_at/resolved_at уже есть,
    отдельное поле было бы дублированием и могло разъехаться.
    """
    def _aware(value: datetime | None) -> datetime | None:
        # Postgres отдаёт со смещением, SQLite — без; приводим к UTC
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    created, claimed, resolved = _aware(task.created_at), _aware(task.claimed_at), _aware(task.resolved_at)
    now = datetime.now(timezone.utc)
    return {
        # от создания до взятия в работу (или до сих пор, если не взята)
        "wait_seconds": int(((claimed or now) - created).total_seconds()) if created else None,
        # от взятия в работу до решения
        "work_seconds": (int((resolved - claimed).total_seconds())
                         if claimed and resolved else None),
        # полное время жизни задачи — это и есть SLA
        "total_seconds": (int((resolved - created).total_seconds())
                          if created and resolved else None),
    }


async def load_context(db: AsyncSession, task: ModerationTask) -> TaskContext:
    recognition = await db.scalar(
        select(Recognition).where(Recognition.id == task.recognition_id))
    if recognition is None:
        raise AppError(409, "conflict", "У задачи нет результата распознавания")

    scan = await db.scalar(select(Scan).options(selectinload(Scan.photos))
                           .where(Scan.id == recognition.scan_id))
    part = (await db.scalar(select(Part).where(Part.id == recognition.part_id))
            if recognition.part_id else None)
    candidates = (await db.execute(
        select(RecognitionCandidate, Part)
        .join(Part, Part.id == RecognitionCandidate.part_id)
        .where(RecognitionCandidate.recognition_id == recognition.id)
        .order_by(RecognitionCandidate.relevance.desc())
    )).all()
    author = await db.scalar(select(User).where(User.id == scan.author_id)) if scan else None
    vessel = await db.scalar(select(Vessel).where(Vessel.id == scan.vessel_id)) if scan else None

    return TaskContext(task=task, recognition=recognition, scan=scan,
                       photos=list(scan.photos) if scan else [],
                       part=part, candidates=[(c, p) for c, p in candidates],
                       author=author, vessel=vessel)


async def list_tasks(db: AsyncSession, *, status: str | None, page: int, page_size: int):
    """Очередь задач. Эксперт видит задачи всех организаций — он внешний
    специалист по железу, а не сотрудник конкретного судовладельца."""
    base = select(ModerationTask)
    if status:
        base = base.where(ModerationTask.status == status)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(
        # Старые задачи вперёд: очередь, а не стек
        base.order_by(ModerationTask.created_at)
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    return list(rows), total


async def get_task(db: AsyncSession, task_id: uuid.UUID) -> ModerationTask:
    task = await db.scalar(select(ModerationTask).where(ModerationTask.id == task_id))
    if task is None:
        raise AppError(404, "not_found", "Задача не найдена")
    return task


async def claim(db: AsyncSession, task: ModerationTask, expert: User) -> ModerationTask:
    """Взять задачу в работу. Повторный claim тем же экспертом безвреден."""
    if task.status == ModerationStatus.resolved.value:
        raise AppError(409, "conflict", "Задача уже решена")
    if task.expert_id and task.expert_id != expert.id:
        # Чужую задачу не перехватываем: два эксперта не должны делать одну работу
        raise AppError(409, "already_claimed",
                       "Задача уже взята другим экспертом",
                       {"expert_id": str(task.expert_id)})

    task.expert_id = expert.id
    task.status = ModerationStatus.in_progress.value
    task.claimed_at = task.claimed_at or datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)
    return task


async def resolve(db: AsyncSession, task: ModerationTask, expert: User, *,
                  resolution: str, correct_part_id: uuid.UUID | None) -> TaskContext:
    """Решение эксперта (FR-HITL-03).

    confirmed — предложенный результат верен;
    corrected — эксперт указал правильную деталь;
    rejected  — деталь определить не удалось.

    Подтверждение и исправление разблокируют downstream: скан снова можно вести
    в закупку и ремонт, потому что Recognition получает статус confirmed/corrected,
    а проверка порога (FR-REC-04) считает такой результат подтверждённым человеком.
    """
    if task.status == ModerationStatus.resolved.value:
        raise AppError(409, "conflict", "Задача уже решена")
    if task.expert_id and task.expert_id != expert.id:
        raise AppError(409, "already_claimed", "Задача взята другим экспертом")

    recognition = await db.scalar(
        select(Recognition).where(Recognition.id == task.recognition_id))
    if recognition is None:
        raise AppError(409, "conflict", "У задачи нет результата распознавания")

    corrected_part: Part | None = None
    if correct_part_id is not None:
        corrected_part = await db.scalar(select(Part).where(Part.id == correct_part_id))
        if corrected_part is None:
            raise AppError(404, "not_found", "Указанная деталь не найдена в каталоге")

    if resolution == ModerationResolution.corrected.value:
        if corrected_part is None:
            raise AppError(422, "validation_error",
                           "Для решения «исправлено» нужно указать правильную деталь")
        recognition.part_id = corrected_part.id
        recognition.status = RecognitionStatus.corrected.value
    elif resolution == ModerationResolution.confirmed.value:
        if recognition.part_id is None and corrected_part is None:
            raise AppError(422, "validation_error",
                           "Подтверждать нечего: деталь не определена. "
                           "Укажите правильную позицию или отклоните.")
        if corrected_part is not None:
            recognition.part_id = corrected_part.id
        recognition.status = RecognitionStatus.confirmed.value
    else:                                                   # rejected
        recognition.status = RecognitionStatus.rejected.value

    scan = await db.scalar(select(Scan).where(Scan.id == recognition.scan_id))
    if scan is not None:
        # confirmed/corrected -> скан готов и разблокирован для закупки и ремонта
        scan.status = (ScanStatus.error if resolution == ModerationResolution.rejected.value
                       else ScanStatus.done).value

    task.status = ModerationStatus.resolved.value
    task.resolution = resolution
    task.corrected_part_id = corrected_part.id if corrected_part else None
    task.expert_id = expert.id
    task.claimed_at = task.claimed_at or datetime.now(timezone.utc)
    task.resolved_at = datetime.now(timezone.utc)
    await db.flush()

    # Решение эксперта — самый качественный обучающий пример (FR-HITL-03, FR-REC-06)
    correct_id = corrected_part.id if corrected_part else (
        recognition.part_id if resolution == ModerationResolution.confirmed.value else None)
    if correct_id is not None:
        exists = await db.scalar(select(TrainingSample).where(
            TrainingSample.recognition_id == recognition.id,
            TrainingSample.correct_part_id == correct_id,
            TrainingSample.source == TrainingSampleSource.expert.value,
        ))
        if exists is None:
            photo_id = None
            if scan is not None:
                photos = list((await db.scalars(
                    select(Photo).where(Photo.scan_id == scan.id))).all())
                nameplate = next((p for p in photos if p.kind == "nameplate"), None)
                photo_id = (nameplate or (photos[0] if photos else None))
                photo_id = photo_id.id if photo_id else None
            db.add(TrainingSample(
                recognition_id=recognition.id, photo_id=photo_id,
                correct_part_id=correct_id, source=TrainingSampleSource.expert.value))

    # Уведомление автору скана (FR-HITL-03, FR-NOT-01)
    if scan is not None:
        await notify_author(db, scan, recognition, resolution, corrected_part)

    await db.commit()
    await db.refresh(task)
    return await load_context(db, task)


_RESOLUTION_TEXT = {
    "confirmed": "Эксперт подтвердил результат распознавания.",
    "corrected": "Эксперт исправил результат: указана другая деталь.",
    "rejected": "Эксперт не смог определить деталь по этим фото. "
                "Попробуйте переснять шильдик крупнее и при лучшем освещении.",
}


async def notify_author(db: AsyncSession, scan: Scan, recognition: Recognition,
                        resolution: str, corrected_part: Part | None) -> Notification:
    """In-app уведомление (FR-NOT-01). Email — следующий этап, см. заглушку ниже."""
    body = _RESOLUTION_TEXT.get(resolution, "Эксперт принял решение по вашему скану.")
    if corrected_part is not None:
        body += f" Верная позиция: {corrected_part.name}"
        if corrected_part.oem_number:
            body += f" ({corrected_part.oem_number})"
        body += "."

    notification = Notification(
        user_id=scan.author_id,
        type="expert_resolved",
        title="Решение эксперта по скану",
        body=body,
        payload={"scan_id": str(scan.id), "recognition_id": str(recognition.id),
                 "resolution": resolution,
                 "part_id": str(corrected_part.id) if corrected_part else None},
    )
    db.add(notification)
    await send_email_stub(scan.author_id, notification.title, body)
    return notification


async def send_email_stub(user_id: uuid.UUID, subject: str, body: str) -> None:
    """Заглушка почтового канала (FR-NOT-01).

    На MVP уведомления только внутри приложения. Точка расширения оставлена
    здесь намеренно: когда появится SMTP, письмо уйдёт отсюда, и остальной код
    менять не придётся.
    """
    return None


async def list_notifications(db: AsyncSession, user: User, *, only_unread: bool,
                             page: int, page_size: int):
    base = select(Notification).where(Notification.user_id == user.id)
    if only_unread:
        base = base.where(Notification.read_at.is_(None))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(
        base.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    unread = await db.scalar(select(func.count()).select_from(
        select(Notification).where(Notification.user_id == user.id,
                                   Notification.read_at.is_(None)).subquery())) or 0
    return list(rows), total, unread


async def mark_read(db: AsyncSession, user: User, notification_id: uuid.UUID) -> Notification:
    notification = await db.scalar(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == user.id))
    if notification is None:
        raise AppError(404, "not_found", "Уведомление не найдено")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(notification)
    return notification
