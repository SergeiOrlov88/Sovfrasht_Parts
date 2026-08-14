# -*- coding: utf-8 -*-
"""Общие фикстуры. Тесты идут на SQLite в файле — Postgres поднимать не нужно."""
import os
import pathlib
import tempfile

import pytest

# Настройки окружения должны быть выставлены ДО импорта приложения
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="sovfrasht_tests_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["APP_ENV"] = "test"
os.environ["ACCESS_TOKEN_TTL_MINUTES"] = "30"
os.environ["REFRESH_TOKEN_TTL_DAYS"] = "14"

# Режим распознавания в тестах закрепляем явно.
# Прод по умолчанию работает в vision_first (ADR-06), но существующие тесты
# описывают ПРЕЖНИЙ контракт ocr_first, и он остаётся поддерживаемым — значит
# должен быть покрыт. Поведение vision_first проверяется отдельно, там режим
# включается точечно (test_recognition_vision_first.py).
os.environ["RECOGNITION_MODE"] = "ocr_first"
# Ни один тест не должен ходить в платный внешний API: провайдеры подменяются
# заглушками, а без ключа реестр и сам вернёт заглушку.
os.environ["VISION_PROVIDER"] = "stub"
os.environ["OPENROUTER_API_KEY"] = ""

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import OrganizationType, Role  # noqa: E402
from app.models.org import Organization, User, Vessel  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
async def _schema():
    """Схема пересоздаётся на каждый тест: тесты меняют данные (отключают
    пользователей, создают новых), и общее состояние ломало бы соседние проверки."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def data(_schema):
    """Две организации — чтобы проверять горизонтальную изоляцию (NFR-SEC-03)."""
    async with SessionLocal() as db:
        org_a = Organization(name="Совфрахт", type=OrganizationType.owner.value)
        org_b = Organization(name="Чужая компания", type=OrganizationType.owner.value)
        db.add_all([org_a, org_b])
        await db.flush()

        vessel_a = Vessel(organization_id=org_a.id, name="Балтика", imo="IMO9111111")
        vessel_a2 = Vessel(organization_id=org_a.id, name="Нева", imo="IMO9333333")
        vessel_b = Vessel(organization_id=org_b.id, name="Чужое судно", imo="IMO9999999")
        db.add_all([vessel_a, vessel_a2, vessel_b])
        await db.flush()

        def mk(org, login, role, vessels=()):
            u = User(organization_id=org.id, login=login, full_name=login,
                     role=role.value, password_hash=hash_password(PASSWORD))
            u.vessels = list(vessels)
            return u

        users = {
            "admin_a": mk(org_a, "admin_a", Role.admin),
            "mech_a": mk(org_a, "mech_a", Role.mechanic, [vessel_a]),
            "supply_a": mk(org_a, "supply_a", Role.supplier_manager),
            "owner_a": mk(org_a, "owner_a", Role.fleet_owner),
            "expert_a": mk(org_a, "expert_a", Role.expert),
            "admin_b": mk(org_b, "admin_b", Role.admin),
            "disabled_a": mk(org_a, "disabled_a", Role.mechanic),
        }
        users["disabled_a"].is_active = False
        db.add_all(users.values())
        await db.commit()

        return {
            "org_a": org_a.id, "org_b": org_b.id,
            "vessel_a": vessel_a.id, "vessel_a2": vessel_a2.id, "vessel_b": vessel_b.id,
            "users": {k: u.id for k, u in users.items()},
        }


async def login(client, login_name: str, password: str = PASSWORD):
    return await client.post("/api/v1/auth/token",
                             json={"login": login_name, "password": password})


async def auth_headers(client, login_name: str) -> dict:
    r = await login(client, login_name)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
