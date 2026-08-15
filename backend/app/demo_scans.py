# -*- coding: utf-8 -*-
"""Демонстрационные сканы для витрины: python -m app.demo_scans

Заводит три скана с разными исходами, чтобы показать все экраны:
  1. уверенное распознавание — отчёт, закупка и ремонт целиком;
  2. низкая достоверность — задача в очереди эксперта;
  3. деталь с вердиктом «ремонт».

Фото — сгенерированные заглушки, загружаются в то же хранилище, что и настоящие,
поэтому подписанные ссылки работают как в реальном сценарии.

Требует уже залитых каталога и пользователей. В prod не запускается.
"""
from __future__ import annotations

import asyncio
import struct
import zlib

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.catalog import Part
from app.models.enums import RecognitionStatus, ScanStatus
from app.models.org import User, Vessel
from app.models.scan import (
    ModerationTask,
    Photo,
    Recognition,
    RecognitionCandidate,
    Scan,
)
from app.services import storage


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Минимальный валидный PNG заданного цвета с рамкой.

    Пишем вручную, чтобы не тащить Pillow ради заглушек: нужен настоящий
    графический файл, иначе браузер покажет битую картинку.
    """
    border = (90, 105, 125)
    rows = bytearray()
    for y in range(height):
        rows.append(0)                                   # фильтр строки: None
        for x in range(width):
            edge = x < 4 or y < 4 or x >= width - 4 or y >= height - 4
            r, g, b = border if edge else rgb
            rows += bytes((r, g, b))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)   # 8 бит, truecolor
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
            + chunk(b"IEND", b""))


PHOTOS = {
    "overview": _png(480, 360, (58, 72, 96)),
    "nameplate": _png(480, 360, (74, 90, 74)),
    "context": _png(480, 360, (96, 78, 58)),
}


async def _add_photo(db, scan: Scan, kind: str) -> Photo:
    content = PHOTOS[kind]
    key = storage.build_storage_key(scan.id, kind, f"{kind}.png")
    await storage.put_object(key, content, "image/png")
    photo = Photo(scan_id=scan.id, storage_key=key, kind=kind, mime_type="image/png",
                  size_bytes=len(content), width=480, height=360,
                  content_sha256=storage.sha256_of(content))
    db.add(photo)
    return photo


async def seed() -> None:
    if settings.is_production:
        raise SystemExit("Демо-сканы не предназначены для окружения prod")

    await storage.ensure_bucket()

    async with SessionLocal() as db:
        mech = await db.scalar(select(User).where(User.login == "mechanic"))
        vessel = await db.scalar(select(Vessel).where(Vessel.imo == "IMO9111111"))
        if mech is None or vessel is None:
            raise SystemExit("Сначала выполните python -m app.seed")

        parts = list((await db.scalars(select(Part))).all())
        by_subtype: dict[str, Part] = {}
        for part in parts:
            subtype = (part.specs or {}).get("subtype")
            if subtype and subtype not in by_subtype:
                by_subtype[subtype] = part
        bosch = next((p for p in parts if p.oem_number_norm == "0445120100"), None)
        man = next((p for p in parts if p.oem_number_norm == "51101006127"), None)
        impeller = by_subtype.get("impeller")
        if bosch is None:
            raise SystemExit("Сначала выполните python -m app.catalog_import")

        created: list[tuple[str, str]] = []

        async def make(client_key: str, *, part, confidence, status, catalog_status,
                       ocr_text, oem_detected, kinds, label,
                       candidate=None, moderation=False):
            if await db.scalar(select(Scan).where(Scan.client_scan_id == client_key)):
                return                                   # идемпотентно
            scan = Scan(vessel_id=vessel.id, author_id=mech.id, status=status.value,
                        client_scan_id=client_key)
            db.add(scan)
            await db.flush()
            for kind in kinds:
                await _add_photo(db, scan, kind)
            rec = Recognition(scan_id=scan.id, part_id=part.id if part else None,
                              confidence=confidence, ocr_text=ocr_text,
                              maker_detected=part.maker if part else None,
                              oem_detected=oem_detected, model_version="yandex_ocr:page",
                              status=RecognitionStatus.auto.value,
                              catalog_status=catalog_status)
            db.add(rec)
            await db.flush()
            if candidate is not None:
                db.add(RecognitionCandidate(recognition_id=rec.id, part_id=candidate.id,
                                            relevance=0.62))
            if moderation:
                db.add(ModerationTask(recognition_id=rec.id, status="pending"))
            created.append((str(scan.id), label))

        await make("demo-confident", part=bosch, confidence=88, status=ScanStatus.done,
                   catalog_status="matched",
                   ocr_text="ROBERT BOSCH GMBH\nPART NO 0445120100\nMADE IN GERMANY",
                   oem_detected="0445120100", kinds=("overview", "nameplate"),
                   label="уверенное распознавание — отчёт, закупка, ремонт")

        await make("demo-needs-expert", part=bosch, confidence=42,
                   status=ScanStatus.needs_review, catalog_status="candidates",
                   ocr_text="BOSCH 044512O1OO 1800BAR", oem_detected="044512O1OO",
                   kinds=("nameplate",), candidate=man, moderation=True,
                   label="низкая достоверность — задача эксперту")

        if impeller is not None:
            await make("demo-repair", part=impeller, confidence=81, status=ScanStatus.done,
                       catalog_status="matched", ocr_text="GRUNDFOS NK impeller",
                       oem_detected=None, kinds=("overview", "context"),
                       label="вердикт «ремонт» на вкладке Ремонт")

        await db.commit()

    if created:
        print("Демо-сканы созданы:")
        for scan_id, label in created:
            print(f"  {scan_id}  — {label}")
    else:
        print("Демо-сканы уже существуют — повторно не создавались.")


if __name__ == "__main__":
    asyncio.run(seed())
