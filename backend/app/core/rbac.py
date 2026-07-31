# -*- coding: utf-8 -*-
"""RBAC (NFR-SEC-03): проверка роли и принадлежности к организации/судну.

Два уровня, и оба обязательны:
  1. вертикальный — роль допущена к эндпоинту (require_roles);
  2. горизонтальный — объект принадлежит организации пользователя (ensure_same_org).
Проверка только на клиенте недопустима (CLAUDE.md).
"""
import uuid
from collections.abc import Callable, Sequence

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.models.enums import Role
from app.models.org import User


def _unauthorized(message: str = "Требуется авторизация") -> AppError:
    err = AppError(401, "unauthorized", message)
    err.headers = {"WWW-Authenticate": "Bearer"}
    return err


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Достаёт пользователя по Bearer-токену и проверяет, что он ещё активен."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()

    try:
        payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Срок действия токена истёк")
    except jwt.InvalidTokenError:
        raise _unauthorized("Некорректный токен")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _unauthorized("Некорректный токен")

    user = await db.scalar(select(User).where(User.id == user_id))
    # Роль могли понизить, а пользователя — отключить уже после выпуска токена,
    # поэтому состояние всегда сверяем с БД, а не доверяем payload.
    if user is None or not user.is_active or user.deleted_at is not None:
        raise _unauthorized("Пользователь недоступен")
    return user


def require_roles(*roles: Role | str) -> Callable:
    """Зависимость: допускает только перечисленные роли."""
    allowed = {r.value if isinstance(r, Role) else str(r) for r in roles}

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise AppError(
                403, "forbidden",
                "Недостаточно прав для этой операции",
                {"required_roles": sorted(allowed), "your_role": user.role},
            )
        return user

    return _dep


def ensure_same_org(user: User, organization_id: uuid.UUID | None) -> None:
    """Горизонтальная защита: чужая организация — 404, а не 403.

    404 намеренно: 403 подтвердил бы существование объекта и позволил перебором
    узнать чужие идентификаторы.
    """
    if organization_id is None or organization_id != user.organization_id:
        raise AppError(404, "not_found", "Объект не найден")


def ensure_vessel_access(user: User, vessel_id: uuid.UUID, vessel_org_id: uuid.UUID,
                         allowed_vessel_ids: Sequence[uuid.UUID] | None = None) -> None:
    """Доступ к судну: сначала организация, затем — для механика — привязка к судну
    (FR-AUTH-03). Остальные роли видят все суда своей организации."""
    ensure_same_org(user, vessel_org_id)
    if user.role == Role.mechanic.value:
        ids = allowed_vessel_ids if allowed_vessel_ids is not None else [v.id for v in user.vessels]
        if vessel_id not in set(ids):
            raise AppError(404, "not_found", "Объект не найден")
