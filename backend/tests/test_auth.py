# -*- coding: utf-8 -*-
"""Аутентификация: вход, токены, refresh (FR-AUTH-01, NFR-SEC-02)."""
import jwt
import pytest

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from tests.conftest import PASSWORD, auth_headers, login


async def test_login_ok(client, data):
    r = await login(client, "mech_a")
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"
    # TTL берётся из окружения — проверяем, что он доезжает до ответа
    assert body["expires_in"] == settings.access_token_ttl_minutes * 60
    assert body["user"]["login"] == "mech_a"
    assert body["user"]["role"] == "mechanic"
    # пароль и его хеш наружу не отдаются
    assert "password" not in body["user"] and "password_hash" not in body["user"]


async def test_login_wrong_password(client, data):
    r = await login(client, "mech_a", "неверный")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


async def test_login_unknown_user_same_answer(client, data):
    """Ответ на несуществующий логин совпадает с ответом на неверный пароль —
    иначе можно перебором выяснять существующие учётные записи."""
    r_unknown = await login(client, "не-существует")
    r_wrong = await login(client, "mech_a", "неверный")
    assert r_unknown.status_code == r_wrong.status_code == 401
    assert r_unknown.json()["error"]["code"] == r_wrong.json()["error"]["code"]


async def test_disabled_user_cannot_login(client, data):
    r = await login(client, "disabled_a")
    assert r.status_code == 401


async def test_me_requires_token(client, data):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_me_returns_role_and_vessels(client, data):
    r = await client.get("/api/v1/auth/me", headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "mechanic"
    assert [v["name"] for v in body["vessels"]] == ["Балтика"]


async def test_refresh_returns_new_access(client, data):
    r = await login(client, "mech_a")
    refresh_token = r.json()["refresh_token"]

    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 200
    assert r2.json()["expires_in"] == settings.access_token_ttl_minutes * 60

    # новый access должен работать
    r3 = await client.get("/api/v1/auth/me",
                          headers={"Authorization": f"Bearer {r2.json()['access_token']}"})
    assert r3.status_code == 200


async def test_access_token_not_accepted_as_refresh(client, data):
    """Типы токенов не взаимозаменяемы."""
    r = await login(client, "mech_a")
    r2 = await client.post("/api/v1/auth/refresh",
                           json={"refresh_token": r.json()["access_token"]})
    assert r2.status_code == 401


async def test_refresh_token_not_accepted_as_access(client, data):
    r = await login(client, "mech_a")
    r2 = await client.get("/api/v1/auth/me",
                          headers={"Authorization": f"Bearer {r.json()['refresh_token']}"})
    assert r2.status_code == 401


async def test_expired_access_token_rejected(client, data, monkeypatch):
    """Срок жизни действительно ограничен (NFR-SEC-02)."""
    monkeypatch.setattr(settings, "access_token_ttl_minutes", -1)
    token = create_access_token(data["users"]["mech_a"], "mechanic", data["org_a"])
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "истёк" in r.json()["error"]["message"]


async def test_token_signed_with_other_key_rejected(client, data):
    """Подделка подписи не проходит."""
    payload = jwt.decode(
        create_access_token(data["users"]["mech_a"], "mechanic", data["org_a"]),
        settings.secret_key, algorithms=[settings.jwt_algorithm],
    )
    forged = jwt.encode(payload, "чужой-ключ", algorithm="HS256")
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_role_escalation_in_token_ignored(client, data):
    """Роль в токене подменена на admin, но в БД пользователь — механик.
    Источник истины — БД, поэтому доступ должен быть закрыт."""
    token = create_access_token(data["users"]["mech_a"], "admin", data["org_a"])
    r = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_refresh_of_deleted_user_rejected(client, data):
    token = create_refresh_token(data["users"]["disabled_a"])
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401


@pytest.mark.parametrize("payload", [{}, {"login": "mech_a"}, {"password": PASSWORD}])
async def test_login_validation_error_format(client, data, payload):
    """Ошибки — в едином формате docs/08 §1."""
    r = await client.post("/api/v1/auth/token", json=payload)
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert "fields" in body["error"]["details"]
