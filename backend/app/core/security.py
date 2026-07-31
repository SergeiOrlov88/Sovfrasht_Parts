# -*- coding: utf-8 -*-
"""Пароли и JWT (NFR-SEC-02).

Пароли — argon2 (современный, устойчив к GPU-перебору). Токены — JWT с коротким
временем жизни access и длинным refresh; TTL задаётся через окружение.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


# ── Пароли ───────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Параметры argon2 со временем ужесточаются — хеш можно обновить при входе."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


# ── JWT ──────────────────────────────────────────────────────────────────────
def _create_token(subject: str, token_type: str, expires_delta: timedelta,
                  extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, role: str, organization_id: uuid.UUID) -> str:
    # Роль и организация кладутся в токен, чтобы RBAC не ходил в БД на каждый запрос.
    # Проверка «пользователь ещё активен» всё равно делается по БД (см. deps.py).
    return _create_token(
        str(user_id),
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.access_token_ttl_minutes),
        {"role": role, "org": str(organization_id)},
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _create_token(
        str(user_id), REFRESH_TOKEN_TYPE, timedelta(days=settings.refresh_token_ttl_days)
    )


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """Расшифровывает и валидирует токен. Бросает jwt-исключения при проблемах."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if expected_type and payload.get("type") != expected_type:
        # Refresh-токен не должен приниматься там, где ждут access, и наоборот.
        raise jwt.InvalidTokenError("Неверный тип токена")
    return payload
