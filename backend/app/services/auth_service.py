# -*- coding: utf-8 -*-
"""Доменная логика аутентификации — вне слоя API (NFR-MAINT-01)."""
import uuid

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.org import User


def _invalid_credentials() -> AppError:
    # Одинаковый ответ и на несуществующий логин, и на неверный пароль —
    # иначе по коду ответа можно перебирать существующие учётные записи.
    err = AppError(401, "invalid_credentials", "Неверный логин или пароль")
    err.headers = {"WWW-Authenticate": "Bearer"}
    return err


async def authenticate(db: AsyncSession, login: str, password: str) -> User:
    """Проверяет логин/пароль (FR-AUTH-01)."""
    user = await db.scalar(select(User).where(User.login == login))
    if user is None or user.deleted_at is not None or not user.is_active:
        raise _invalid_credentials()
    if not verify_password(password, user.password_hash):
        raise _invalid_credentials()

    # Прозрачно обновляем хеш, если параметры argon2 ужесточились
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        await db.commit()
    return user


def issue_tokens(user: User) -> tuple[str, str, int]:
    """Возвращает (access, refresh, время жизни access в секундах)."""
    access = create_access_token(user.id, user.role, user.organization_id)
    refresh = create_refresh_token(user.id)
    return access, refresh, settings.access_token_ttl_minutes * 60


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> tuple[str, int]:
    """Обменивает refresh на новый access (docs/08 §2)."""
    try:
        payload = decode_token(refresh_token, expected_type=REFRESH_TOKEN_TYPE)
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Срок действия refresh-токена истёк")
    except jwt.InvalidTokenError:
        raise AppError(401, "invalid_token", "Некорректный refresh-токен")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise AppError(401, "invalid_token", "Некорректный refresh-токен")

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AppError(401, "unauthorized", "Пользователь недоступен")

    # Роль берём из БД: если её изменили, новый access должен это учесть
    access = create_access_token(user.id, user.role, user.organization_id)
    return access, settings.access_token_ttl_minutes * 60
