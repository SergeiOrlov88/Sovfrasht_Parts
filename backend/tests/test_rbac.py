# -*- coding: utf-8 -*-
"""RBAC: вертикальные права по ролям и горизонтальная изоляция организаций (NFR-SEC-03)."""
import pytest

from tests.conftest import auth_headers

# ── Вертикально: роль допущена к эндпоинту ───────────────────────────────────


@pytest.mark.parametrize("who,expected", [
    ("admin_a", 200),
    ("mech_a", 403),
    ("supply_a", 403),
    ("owner_a", 403),
    ("expert_a", 403),
])
async def test_users_list_only_for_admin(client, data, who, expected):
    r = await client.get("/api/v1/users", headers=await auth_headers(client, who))
    assert r.status_code == expected


@pytest.mark.parametrize("who,expected", [
    ("admin_a", 200),
    ("owner_a", 200),
    ("mech_a", 403),
    ("supply_a", 403),
    ("expert_a", 403),
])
async def test_vessels_list_for_admin_and_owner(client, data, who, expected):
    r = await client.get("/api/v1/vessels", headers=await auth_headers(client, who))
    assert r.status_code == expected


async def test_forbidden_payload_explains_requirement(client, data):
    r = await client.get("/api/v1/users", headers=await auth_headers(client, "mech_a"))
    body = r.json()["error"]
    assert body["code"] == "forbidden"
    assert body["details"]["your_role"] == "mechanic"
    assert "admin" in body["details"]["required_roles"]


# ── Горизонтально: чужая организация недоступна ──────────────────────────────

async def test_users_list_scoped_to_own_organization(client, data):
    r = await client.get("/api/v1/users", headers=await auth_headers(client, "admin_a"))
    logins = {u["login"] for u in r.json()["items"]}
    assert "admin_b" not in logins            # чужая организация не видна
    assert {"admin_a", "mech_a"} <= logins


async def test_vessels_list_scoped_to_own_organization(client, data):
    r = await client.get("/api/v1/vessels", headers=await auth_headers(client, "admin_a"))
    names = {v["name"] for v in r.json()["items"]}
    assert "Чужое судно" not in names
    assert {"Балтика", "Нева"} <= names


async def test_cannot_patch_foreign_user(client, data):
    """Чужой пользователь -> 404 (не 403): 403 подтвердил бы его существование."""
    r = await client.patch(
        f"/api/v1/users/{data['users']['admin_b']}",
        json={"full_name": "взлом"},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 404


async def test_cannot_patch_foreign_vessel(client, data):
    r = await client.patch(
        f"/api/v1/vessels/{data['vessel_b']}",
        json={"name": "взлом"},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 404


async def test_cannot_attach_foreign_vessel_to_user(client, data):
    """Привязка к судну чужой организации должна отклоняться."""
    r = await client.post(
        "/api/v1/users",
        json={"login": "newbie", "full_name": "Новый", "password": "password123",
              "role": "mechanic", "vessel_ids": [str(data["vessel_b"])]},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 422


# ── Администрирование ────────────────────────────────────────────────────────

async def test_create_user_lands_in_admin_organization(client, data):
    r = await client.post(
        "/api/v1/users",
        json={"login": "mech_new", "full_name": "Новый механик", "password": "password123",
              "role": "mechanic", "vessel_ids": [str(data["vessel_a2"])]},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["organization_id"] == str(data["org_a"])
    assert [v["name"] for v in body["vessels"]] == ["Нева"]

    # созданный пользователь может войти заданным паролем
    r2 = await client.post("/api/v1/auth/token",
                           json={"login": "mech_new", "password": "password123"})
    assert r2.status_code == 200


async def test_duplicate_login_conflict(client, data):
    r = await client.post(
        "/api/v1/users",
        json={"login": "mech_a", "full_name": "Дубль", "password": "password123",
              "role": "mechanic"},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_admin_cannot_disable_self(client, data):
    r = await client.patch(
        f"/api/v1/users/{data['users']['admin_a']}",
        json={"is_active": False},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 422


async def test_deactivated_user_loses_access_immediately(client, data):
    """Токен выпущен до отключения — доступ всё равно должен закрыться."""
    headers = await auth_headers(client, "supply_a")
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    r = await client.patch(
        f"/api/v1/users/{data['users']['supply_a']}",
        json={"is_active": False},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 200

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_vessel_imo_unique_within_organization(client, data):
    r = await client.post(
        "/api/v1/vessels",
        json={"name": "Дубль IMO", "imo": "IMO9111111"},
        headers=await auth_headers(client, "admin_a"),
    )
    assert r.status_code == 409
