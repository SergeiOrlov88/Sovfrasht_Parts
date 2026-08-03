# -*- coding: utf-8 -*-
"""Панель эксперта (F2) и уведомления, docs/08 §8-9.

Доступ к модерации — только роли expert и admin, и проверяется он на сервере:
скрыть раздел в интерфейсе недостаточно (NFR-SEC-03, CLAUDE.md).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import get_current_user, require_roles
from app.models.enums import ModerationStatus, Role
from app.models.org import User
from app.schemas.moderation import (
    ModerationTaskPage,
    ModerationTaskRead,
    NotificationPage,
    NotificationRead,
    ResolveRequest,
    SlaRead,
)
from app.schemas.scan import CandidateRead, PartBrief, RecognitionRead
from app.services import moderation_service, scan_service

router = APIRouter(tags=["moderation"])

# Эксперт — основная роль; админ допущен, чтобы разбирать зависшие задачи
_expert_roles = require_roles(Role.expert, Role.admin)


async def _to_read(db: AsyncSession, task) -> ModerationTaskRead:
    ctx = await moderation_service.load_context(db, task)
    return ModerationTaskRead(
        id=task.id,
        status=ModerationStatus(task.status),
        resolution=task.resolution,
        expert_id=task.expert_id,
        created_at=task.created_at,
        claimed_at=task.claimed_at,
        resolved_at=task.resolved_at,
        sla=SlaRead(**moderation_service.sla_seconds(task)),
        scan_id=ctx.scan.id if ctx.scan else None,
        vessel_name=ctx.vessel.name if ctx.vessel else None,
        author_name=ctx.author.full_name if ctx.author else None,
        recognition=RecognitionRead.model_validate(ctx.recognition),
        part=PartBrief.model_validate(ctx.part) if ctx.part else None,
        candidates=[
            CandidateRead(part=PartBrief.model_validate(p), relevance=c.relevance or 0.0)
            for c, p in ctx.candidates
        ],
        # Фото — по подписанным ссылкам, прямого доступа к бакету нет (NFR-SEC-04)
        photos=await scan_service.with_signed_urls(ctx.photos),
    )


@router.get("/moderation/tasks", response_model=ModerationTaskPage,
            summary="Очередь задач эксперта")
async def list_tasks(
    status_filter: ModerationStatus | None = Query(ModerationStatus.pending, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    expert: User = Depends(_expert_roles),
    db: AsyncSession = Depends(get_db),
) -> ModerationTaskPage:
    rows, total = await moderation_service.list_tasks(
        db, status=status_filter.value if status_filter else None,
        page=page, page_size=page_size)
    return ModerationTaskPage(items=[await _to_read(db, t) for t in rows],
                              total=total, page=page, page_size=page_size)


@router.get("/moderation/tasks/{task_id}", response_model=ModerationTaskRead,
            summary="Задача модерации")
async def get_task(task_id: uuid.UUID, expert: User = Depends(_expert_roles),
                   db: AsyncSession = Depends(get_db)) -> ModerationTaskRead:
    return await _to_read(db, await moderation_service.get_task(db, task_id))


@router.post("/moderation/tasks/{task_id}/claim", response_model=ModerationTaskRead,
             summary="Взять задачу в работу")
async def claim_task(task_id: uuid.UUID, expert: User = Depends(_expert_roles),
                     db: AsyncSession = Depends(get_db)) -> ModerationTaskRead:
    task = await moderation_service.get_task(db, task_id)
    task = await moderation_service.claim(db, task, expert)
    return await _to_read(db, task)


@router.post("/moderation/tasks/{task_id}/resolve", response_model=ModerationTaskRead,
             summary="Решение эксперта")
async def resolve_task(
    task_id: uuid.UUID,
    payload: ResolveRequest,
    expert: User = Depends(_expert_roles),
    db: AsyncSession = Depends(get_db),
) -> ModerationTaskRead:
    """Подтверждение или исправление разблокирует скан для закупки и ремонта
    (FR-HITL-03); автор получает уведомление (FR-NOT-01)."""
    task = await moderation_service.get_task(db, task_id)
    ctx = await moderation_service.resolve(
        db, task, expert,
        resolution=payload.resolution.value, correct_part_id=payload.correct_part_id)
    return await _to_read(db, ctx.task)


# ── Уведомления (docs/08 §9) ─────────────────────────────────────────────────

@router.get("/notifications", response_model=NotificationPage, summary="Мои уведомления")
async def list_notifications(
    unread: bool = Query(False, description="только непрочитанные"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPage:
    rows, total, unread_count = await moderation_service.list_notifications(
        db, user, only_unread=unread, page=page, page_size=page_size)
    return NotificationPage(items=[NotificationRead.model_validate(n) for n in rows],
                            total=total, unread=unread_count, page=page, page_size=page_size)


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead,
             summary="Отметить уведомление прочитанным")
async def read_notification(notification_id: uuid.UUID,
                            user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)) -> NotificationRead:
    return NotificationRead.model_validate(
        await moderation_service.mark_read(db, user, notification_id))
