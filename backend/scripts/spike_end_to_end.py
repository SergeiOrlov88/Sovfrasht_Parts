# -*- coding: utf-8 -*-
"""Сквозной прогон vision_first: скан -> конвейер -> ответ API отчёта.

Без Docker: БД — SQLite в файле (как в тестах), фото читаются с диска вместо
MinIO. Проверяем главное, ради чего затевался разворот: деталь, которой НЕТ в
каталоге, всё равно получает содержательный отчёт «что это», а не «не определена».

Запуск:
    cd backend
    .venv/Scripts/python.exe spike_end_to_end.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
import uuid

# Настройки окружения — ДО импорта приложения (как в tests/conftest.py)
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="sovfrasht_e2e_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'e2e.db').as_posix()}"
os.environ["SECRET_KEY"] = "e2e-secret-not-for-production"
os.environ["APP_ENV"] = "test"

from sqlalchemy import select                                # noqa: E402
from sqlalchemy.orm import selectinload                      # noqa: E402

import app.services.storage as storage                      # noqa: E402
from app.core.database import Base, SessionLocal, engine     # noqa: E402
from app.core.config import settings                         # noqa: E402
from app.models.enums import OrganizationType, PhotoKind, Role, ScanStatus  # noqa: E402
from app.models.org import Organization, User, Vessel        # noqa: E402
from app.models.scan import Photo, Scan                      # noqa: E402
from app.core.security import hash_password                  # noqa: E402
from app.services import recognition_service                 # noqa: E402
from app.api.v1.endpoints.scans import get_report            # noqa: E402

# Скрипт лежит в backend/scripts/, фото — в photos/ в корне проекта
PHOTOS = pathlib.Path(__file__).resolve().parent.parent.parent / "photos"

# Какие кадры считаем одной деталью. Ровно так работает приложение: все кадры
# скана уходят в модель ОДНИМ запросом.
SCANS = [
    ("Sperry (гирокомпас): шильдик + общий вид",
     [("IMG-20260616-WA0037.jpg", PhotoKind.nameplate),
      ("IMG-20260616-WA0036.jpg", PhotoKind.overview)]),
    ("Graviner MK5 OMD: шильдик",
     [("IMG-20260703-WA0102(1).jpg", PhotoKind.nameplate)]),
]

_FILES: dict[str, bytes] = {}          # storage_key -> содержимое файла


def _fake_get_object_sync(key: str) -> bytes:
    """Подмена MinIO: конвейер читает те же байты, что лежат в photos/."""
    return _FILES[key]


async def main() -> int:
    if not PHOTOS.exists():
        print(f"Каталог с фото не найден: {PHOTOS}")
        return 2
    if not settings.openrouter_api_key:
        print("OPENROUTER_API_KEY пуст — прогон невозможен")
        return 2

    storage.get_object_sync = _fake_get_object_sync
    recognition_service.storage.get_object_sync = _fake_get_object_sync

    print(f"режим распознавания: {settings.recognition_mode}")
    print(f"vision-провайдер:    {settings.vision_provider} / {settings.openrouter_model}")
    print(f"OCR-провайдер:       {settings.ocr_provider} "
          f"(ключа нет -> заглушка, как на демо)")
    print(f"порог эксперта:      {settings.confidence_threshold}")
    print()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        org = Organization(name="Совфрахт", type=OrganizationType.owner.value)
        db.add(org)
        await db.flush()
        vessel = Vessel(organization_id=org.id, name="Балтика", imo="IMO9111111")
        user = User(organization_id=org.id, login="mech",
                    full_name="Механик", role=Role.mechanic.value,
                    password_hash=hash_password("x"))
        db.add_all([vessel, user])
        await db.flush()
        # Связь загружаем явно: в async-сессии ленивая подгрузка падает
        # (MissingGreenlet) — обращаться к user.vessels без загрузки нельзя
        loaded = await db.scalar(
            select(User).options(selectinload(User.vessels)).where(User.id == user.id)
        )
        loaded.vessels.append(vessel)
        await db.commit()
        org_id, vessel_id, user_id = org.id, vessel.id, user.id

    for title, frames in SCANS:
        missing = [n for n, _ in frames if not (PHOTOS / n).exists()]
        if missing:
            print(f"ПРОПУСК «{title}»: нет файлов {missing}")
            continue

        async with SessionLocal() as db:
            scan = Scan(vessel_id=vessel_id, author_id=user_id,
                        status=ScanStatus.queued.value, client_scan_id=str(uuid.uuid4()))
            db.add(scan)
            await db.flush()
            for name, kind in frames:
                content = (PHOTOS / name).read_bytes()
                key = storage.build_storage_key(scan.id, kind.value, name)
                _FILES[key] = content
                db.add(Photo(scan_id=scan.id, kind=kind.value, storage_key=key,
                             mime_type="image/jpeg", size_bytes=len(content),
                             content_sha256=storage.sha256_of(content)))
            await db.commit()
            scan_id = scan.id

        print("=" * 78)
        print(f"СКАН: {title}")
        print(f"  кадров в запросе к модели: {len(frames)}")
        print("=" * 78)

        async with SessionLocal() as db:
            outcome = await recognition_service.run_pipeline(db, scan_id)

        print(f"  статус скана:   {outcome.scan_status.value}")
        print(f"  confidence:     {outcome.confidence}")
        print(f"  каталог:        {outcome.catalog_status}")
        print(f"  нужен эксперт:  {outcome.needs_expert}")
        print(f"  модель:         {outcome.model_version}")
        print()

        # Ответ РЕАЛЬНОГО эндпоинта отчёта — то, что увидит фронтенд
        async with SessionLocal() as db:
            current = await db.get(User, user_id)
            report = await get_report(scan_id, user=current, db=db)

        print("  ── что увидит механик в отчёте ──")
        print(f"  Заголовок:  {(report.identification.title if report.identification else None) or (report.part.name if report.part else 'Деталь не определена')}")
        if report.identification:
            i = report.identification
            print(f"  Тип:        {i.part_type or '—'}")
            print(f"  Изготовитель:{i.maker or '—'}")
            print(f"  Модель:     {i.model or '—'}")
            print(f"  Назначение: {i.function or '—'}")
            print(f"  Маркировка: {i.markings or '—'}")
            print(f"  Уверенность модели: {i.confidence}")
            print(f"  Оговорки:   {i.notes or '—'}")
        else:
            print("  опознание ОТСУТСТВУЕТ — отчёт покажет «не определена»")
        print(f"  Позиция каталога: {report.part.name if report.part else 'нет'}")
        print(f"  Сообщение:  {report.message}")
        print(f"  Плашка/предупреждение: {report.warning or '—'}")
        print(f"  Кнопка «отправить эксперту»: {report.can_request_expert}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
