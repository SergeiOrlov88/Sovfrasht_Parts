# -*- coding: utf-8 -*-
"""Управление пользователями (docs/08 §3, FR-AUTH-04). Роль: admin."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.rbac import require_roles
from app.core.security import hash_password
from app.models.enums import Role
from app.models.org import User, Vessel
from app.schemas.admin import UserCreate, UserPage, UserUpdate
from app.schemas.auth import UserRead

router = APIRouter(tags=["users"])


async def _load_vessels(db: AsyncSession, org_id: uuid.UUID,
                        vessel_ids: list[uuid.UUID]) -> list[Vessel]:
    """Привязывать можно только суда своей организации (NFR-SEC-03)."""
    if not vessel_ids:
        return []
    rows = (await db.scalars(
        select(Vessel).where(Vessel.id.in_(vessel_ids), Vessel.organization_id == org_id)
    )).all()
    if len(rows) != len(set(vessel_ids)):
        raise AppError(422, "validation_error", "Некоторые суда не найдены в вашей организации")
    return list(rows)


@router.get("/users", response_model=UserPage, summary="Список пользователей организации")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_roles(Role.admin)),
    db: AsyncSession = Depends(get_db),
) -> UserPage:
    # Скоуп по организации — иначе admin одной компании увидит чужих людей
    base = select(User).where(
        User.organization_id == admin.organization_id, User.deleted_at.is_(None)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(
        base.order_by(User.created_at).offset((page - 1) * page_size).limit(page_size)
    )).all()
    return UserPage(items=[UserRead.model_validate(u) for u in rows],
                    total=total, page=page, page_size=page_size)


@router.post("/users", response_model=UserRead, status_code=201, summary="Создать пользователя")
async def create_user(
    payload: UserCreate,
    admin: User = Depends(require_roles(Role.admin)),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    if await db.scalar(select(User).where(User.login == payload.login)):
        raise AppError(409, "conflict", "Пользователь с таким логином уже существует")

    user = User(
        organization_id=admin.organization_id,      # только своя организация
        login=payload.login,
        full_name=payload.full_name,
        role=payload.role.value,
        password_hash=hash_password(payload.password),
    )
    user.vessels = await _load_vessels(db, admin.organization_id, payload.vessel_ids)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserRead, summary="Изменить пользователя")
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: User = Depends(require_roles(Role.admin)),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    # Чужая организация -> 404, чтобы перебором нельзя было выяснить чужие id
    if user is None or user.organization_id != admin.organization_id:
        raise AppError(404, "not_found", "Пользователь не найден")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.role is not None:
        user.role = payload.role.value
    if payload.is_active is not None:
        if user.id == admin.id and payload.is_active is False:
            raise AppError(422, "validation_error", "Нельзя отключить собственную учётную запись")
        user.is_active = payload.is_active
    if payload.vessel_ids is not None:
        user.vessels = await _load_vessels(db, admin.organization_id, payload.vessel_ids)

    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)
