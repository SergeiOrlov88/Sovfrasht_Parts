# -*- coding: utf-8 -*-
"""Приём сканов: валидация фото, идемпотентность, запись в хранилище (A1)."""
from __future__ import annotations

import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import AppError
from app.models.enums import PhotoKind, ScanStatus
from app.models.org import User, Vessel
from app.models.scan import Photo, Scan
from app.schemas.scan import ScanCreateMeta
from app.services import storage

# Порядок соответствует FR-CAP-01: общий вид, шильдик, место установки
_DEFAULT_KINDS = [PhotoKind.overview, PhotoKind.nameplate, PhotoKind.context]


async def _assert_vessel_access(db: AsyncSession, user: User, vessel_id: uuid.UUID) -> Vessel:
    """Судно должно быть своей организации, а механик — быть к нему привязан
    (FR-AUTH-03, NFR-SEC-03). Чужое судно -> 404, чтобы не подтверждать его существование."""
    vessel = await db.scalar(select(Vessel).where(Vessel.id == vessel_id))
    if vessel is None or vessel.organization_id != user.organization_id:
        raise AppError(404, "not_found", "Судно не найдено")
    if user.role == "mechanic" and vessel.id not in {v.id for v in user.vessels}:
        raise AppError(404, "not_found", "Судно не найдено")
    return vessel


def _validate_photos(files: list[UploadFile], contents: list[bytes]) -> None:
    """Проверка типа и размера файлов (NFR-SEC-04, FR-CAP-01)."""
    if not files:
        raise AppError(422, "validation_error", "Нужно приложить хотя бы одно фото")
    if len(files) > settings.max_photos_per_scan:
        raise AppError(
            422, "validation_error",
            f"Не более {settings.max_photos_per_scan} фото на скан",
            {"received": len(files)},
        )
    allowed = settings.allowed_photo_mime_set
    for file, content in zip(files, contents):
        mime = (file.content_type or "").lower()
        if mime not in allowed:
            raise AppError(422, "validation_error",
                           f"Неподдерживаемый тип файла: {mime or 'не указан'}",
                           {"allowed": sorted(allowed)})
        if not content:
            raise AppError(422, "validation_error", "Пустой файл не принимается")
        if len(content) > settings.max_photo_size_bytes:
            raise AppError(413, "payload_too_large",
                           f"Файл больше {settings.max_photo_size_mb} МБ",
                           {"filename": file.filename})


async def find_by_client_key(db: AsyncSession, author_id: uuid.UUID,
                             client_scan_id: str | None) -> Scan | None:
    """Идемпотентность (NFR-REL-04): тот же ключ -> тот же скан, дубль не создаём."""
    if not client_scan_id:
        return None
    return await db.scalar(
        select(Scan)
        .options(selectinload(Scan.photos))
        .where(Scan.author_id == author_id, Scan.client_scan_id == client_scan_id)
    )


async def create_scan(db: AsyncSession, user: User, meta: ScanCreateMeta,
                      files: list[UploadFile], kinds: list[str] | None = None) -> Scan:
    """Создаёт скан с фото. Файлы кладутся в MinIO, в БД — только ключи."""
    await _assert_vessel_access(db, user, meta.vessel_id)

    contents = [await f.read() for f in files]
    _validate_photos(files, contents)

    scan = Scan(
        vessel_id=meta.vessel_id,
        author_id=user.id,
        client_scan_id=meta.client_scan_id,
        status=ScanStatus.queued.value,
        geo_lat=meta.geo.lat if meta.geo else None,
        geo_lon=meta.geo.lon if meta.geo else None,
    )
    db.add(scan)
    await db.flush()                       # нужен scan.id для ключей в хранилище

    await storage.ensure_bucket()
    for index, (file, content) in enumerate(zip(files, contents)):
        kind = (kinds[index] if kinds and index < len(kinds) and kinds[index]
                else _DEFAULT_KINDS[min(index, len(_DEFAULT_KINDS) - 1)].value)
        key = storage.build_storage_key(scan.id, kind, file.filename or "photo.jpg")
        await storage.put_object(key, content, file.content_type or "application/octet-stream")
        db.add(Photo(
            scan_id=scan.id,
            storage_key=key,
            kind=kind,
            mime_type=(file.content_type or "").lower() or None,
            size_bytes=len(content),
            content_sha256=storage.sha256_of(content),
        ))

    await db.commit()
    await db.refresh(scan, attribute_names=["photos"])
    return scan


async def with_signed_urls(photos: list[Photo]) -> list[dict]:
    """Добавляет к фото временные ссылки. Сбой подписи не должен ронять ответ."""
    result = []
    for photo in photos:
        try:
            url = await storage.presigned_url(photo.storage_key)
        except storage.StorageError:
            url = None
        result.append({
            "id": photo.id, "kind": photo.kind, "width": photo.width,
            "height": photo.height, "size_bytes": photo.size_bytes, "url": url,
        })
    return result
