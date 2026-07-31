# -*- coding: utf-8 -*-
"""Демо-данные для локальной разработки: организация, суда, по пользователю на роль.

Запуск:  python -m app.seed
Пароли берутся из SEED_PASSWORD (по умолчанию 'demo12345') — только для локального
окружения. В prod сидер не запускается: он отказывается работать при APP_ENV=prod.
"""
import asyncio
import os

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.enums import OrganizationType, Role
from app.models.org import Organization, User, Vessel

SEED_PASSWORD = os.getenv("SEED_PASSWORD", "demo12345")

USERS = [
    ("admin",    "Администратор системы",    Role.admin,            []),
    ("mechanic", "Иванов И. И., механик",    Role.mechanic,         ["IMO9111111"]),
    ("supply",   "Петров П. П., снабженец",  Role.supplier_manager, []),
    ("owner",    "Сидоров С. С., судовладелец", Role.fleet_owner,   []),
    ("expert",   "Кузнецов К. К., эксперт",  Role.expert,           []),
]

VESSELS = [
    ("Балтика",     "IMO9111111", "Сухогруз"),
    ("Севморпуть-2", "IMO9222222", "Танкер"),
]


async def seed() -> None:
    if settings.is_production:
        raise SystemExit("Сидер не предназначен для окружения prod")

    async with SessionLocal() as db:
        org = await db.scalar(select(Organization).where(Organization.name == "Совфрахт"))
        if org is None:
            org = Organization(name="Совфрахт", type=OrganizationType.owner.value)
            db.add(org)
            await db.flush()

        vessels: dict[str, Vessel] = {}
        for name, imo, vtype in VESSELS:
            v = await db.scalar(
                select(Vessel).where(Vessel.organization_id == org.id, Vessel.imo == imo)
            )
            if v is None:
                v = Vessel(organization_id=org.id, name=name, imo=imo, type=vtype)
                db.add(v)
                await db.flush()
            vessels[imo] = v

        created = []
        for login, full_name, role, imos in USERS:
            if await db.scalar(select(User).where(User.login == login)):
                continue
            user = User(
                organization_id=org.id,
                login=login,
                full_name=full_name,
                role=role.value,
                password_hash=hash_password(SEED_PASSWORD),
            )
            user.vessels = [vessels[i] for i in imos if i in vessels]
            db.add(user)
            created.append(login)

        await db.commit()

    print(f"Организация: {org.name}")
    print(f"Суда: {', '.join(n for n, _, _ in VESSELS)}")
    print(f"Созданы пользователи: {', '.join(created) if created else '— (уже существовали)'}")
    print(f"Пароль у всех: {SEED_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
