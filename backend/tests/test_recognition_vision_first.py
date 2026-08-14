# -*- coding: utf-8 -*-
"""Режим vision_first: опознание есть даже без каталога (ADR-06, FR-REC-01a).

Смысл проверок — зафиксировать разворот, вскрытый на демо: деталь, которой нет
в каталоге из 57 позиций, обязана получить содержательный ответ «что это»,
а не «не определена».
"""
import uuid

import pytest

from app.adapters.vision import registry
from app.adapters.vision.base import OcrResult, VisionResult
from app.core.config import settings
from app.services import recognition_service, report_service, storage

pytestmark = pytest.mark.asyncio


@pytest.fixture
def stub_storage(monkeypatch):
    monkeypatch.setattr(storage, "get_object_sync", lambda key: b"\x89PNG\r\n\x1a\nbytes")


def _identified() -> VisionResult:
    """Ответ модели на реальной детали вне каталога (Graviner MK5 OMD)."""
    return VisionResult(
        description="Graviner MK5 OMD датчик масляного тумана",
        category="датчик масляного тумана",
        maker="Graviner",
        model_version="openrouter_vision:openai/gpt-4o",
        confidence=85,
        part_type="датчик масляного тумана",
        model="MK5 OMD",
        function="Обнаруживает масляный туман в картере, предотвращая взрыв.",
        markings="MK5 GRAVINER OMD Pt. No. 53561-221 SER. No. 1780",
        notes="На фото виден только шильдик.",
    )


def _patch(monkeypatch, ocr: OcrResult, vision: VisionResult):
    class _Ocr:
        name = "fake_ocr"

        async def recognize_text(self, photo):
            return ocr

    class _Vision:
        name = "fake_vision"
        calls = 0

        async def describe(self, photos):
            _Vision.calls += 1
            # Ключевое требование FR-REC-01: в модель уходят ВСЕ кадры скана
            _Vision.last_photo_count = len(photos)
            return vision

    monkeypatch.setattr(settings, "recognition_mode", "vision_first")
    for module in (registry, recognition_service):
        monkeypatch.setattr(module, "get_ocr_provider", lambda: _Ocr())
        monkeypatch.setattr(module, "get_vision_provider", lambda: _Vision())
    return _Vision


async def _make_scan(db, vessel_id, author_id, kinds=("nameplate",)):
    from app.models.enums import ScanStatus
    from app.models.scan import Photo, Scan

    scan = Scan(vessel_id=vessel_id, author_id=author_id,
                status=ScanStatus.queued.value, client_scan_id=str(uuid.uuid4()))
    db.add(scan)
    await db.flush()
    for i, kind in enumerate(kinds):
        db.add(Photo(scan_id=scan.id, kind=kind, storage_key=f"k{i}",
                     mime_type="image/jpeg", size_bytes=10, content_sha256=f"sha{i}"))
    await db.commit()
    return scan.id


async def test_identified_part_absent_from_catalog_still_answers(
        data, stub_storage, monkeypatch):
    """Каталог пуст, но отчёт обязан сказать, что это за деталь."""
    from app.core.database import SessionLocal

    _patch(monkeypatch, OcrResult(text=""), _identified())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"])
        outcome = await recognition_service.run_pipeline(db, scan_id)

    # Каталога нет — но это больше не приговор
    assert outcome.catalog_status == "not_found"
    # Доверие взято от модели и НЕ срезано отсутствием позиции в каталоге
    assert outcome.confidence == 85

    async with SessionLocal() as db:
        from sqlalchemy import select
        from app.models.scan import Recognition
        rec = await db.scalar(select(Recognition).where(Recognition.scan_id == scan_id))
        ident = report_service.extract_identification(rec)

    assert ident is not None, "опознание должно попасть в отчёт"
    assert ident["part_type"] == "датчик масляного тумана"
    assert ident["maker"] == "Graviner"
    assert ident["model"] == "MK5 OMD"
    assert "картер" in ident["function"]
    assert "53561-221" in ident["markings"]
    assert ident["title"]


async def test_all_frames_go_to_model_in_one_request(data, stub_storage, monkeypatch):
    """Шильдик и общий вид уходят одним запросом — это повышает точность."""
    from app.core.database import SessionLocal

    fake_vision = _patch(monkeypatch, OcrResult(text=""), _identified())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"],
                                   kinds=("nameplate", "overview", "context"))
        await recognition_service.run_pipeline(db, scan_id)

    assert fake_vision.calls == 1, "модель должна вызываться один раз на скан"
    assert fake_vision.last_photo_count == 3, "в запрос должны войти все три кадра"


async def test_number_from_markings_used_for_catalog(data, stub_storage, monkeypatch):
    """OCR промахнулся, но номер прочитала модель — он идёт в каталог."""
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.models.scan import Recognition

    _patch(monkeypatch, OcrResult(text=""), _identified())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"])
        await recognition_service.run_pipeline(db, scan_id)
        rec = await db.scalar(select(Recognition).where(Recognition.scan_id == scan_id))

    # Номер извлечён из markings разбором шильдика, а не потерян
    assert rec.oem_detected, "номер из маркировки должен сохраниться"


async def test_ocr_first_mode_still_supported(data, stub_storage, monkeypatch):
    """Откат на прежнее поведение остаётся рабочим: отсутствие в каталоге снижает доверие."""
    from app.core.database import SessionLocal

    class _Ocr:
        name = "fake_ocr"

        async def recognize_text(self, photo):
            return OcrResult(text="GRAVINER MK5 OMD 53561-221", maker="Graviner",
                             oem_number="53561-221", model_version="fake:1")

    class _Vision:
        name = "fake_vision"

        async def describe(self, photos):
            raise AssertionError("в ocr_first vision не должен вызываться при читаемом шильдике")

    monkeypatch.setattr(settings, "recognition_mode", "ocr_first")
    for module in (registry, recognition_service):
        monkeypatch.setattr(module, "get_ocr_provider", lambda: _Ocr())
        monkeypatch.setattr(module, "get_vision_provider", lambda: _Vision())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"])
        outcome = await recognition_service.run_pipeline(db, scan_id)

    assert outcome.used_fallback is False
