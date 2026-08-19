# -*- coding: utf-8 -*-
"""Съёмка без шильдика (FR-CAP-06, FR-REC-07).

Смысл проверок — зафиксировать, что отсутствие таблички больше не блокирует
работу, но и не выдаёт себя за подтверждённое опознание: точная закупка по
артикулу возможна только когда номер подтверждён каталогом.
"""
import uuid

import pytest

from app.adapters.vision import registry
from app.adapters.vision.base import OcrResult, VisionResult
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.enums import IdentificationBasis
from app.services import catalog_import, recognition_service, storage

pytestmark = pytest.mark.asyncio


@pytest.fixture
def stub_storage(monkeypatch):
    monkeypatch.setattr(storage, "get_object_sync", lambda key: b"\x89PNG\r\n\x1a\nbytes")


def _by_appearance() -> VisionResult:
    """Снят только общий вид: модель узнаёт тип, номера на фото нет."""
    return VisionResult(
        description="Центробежный насос забортной воды",
        category="насос",
        maker="GRUNDFOS",
        model_version="openrouter_vision:openai/gpt-4o",
        confidence=82,
        part_type="насос центробежный",
        model=None,
        function="Прокачивает забортную воду через холодильники ГД.",
        markings=None,
        notes="Таблички в кадре нет, вывод по форме корпуса и патрубкам.",
    )


def _with_number() -> VisionResult:
    """Номер прочитан — неважно, с таблички или выбитый на корпусе."""
    return VisionResult(
        description="Форсунка Common Rail",
        category="форсунка",
        maker="BOSCH",
        model_version="openrouter_vision:openai/gpt-4o",
        confidence=88,
        part_type="форсунка",
        model="0445120123",
        function="Впрыск топлива в цилиндр.",
        markings="BOSCH 0445120123",
        notes=None,
    )


def _patch(monkeypatch, vision: VisionResult, ocr_text: str = ""):
    class _Ocr:
        name = "fake_ocr"

        async def recognize_text(self, photo):
            return OcrResult(text=ocr_text)

    class _Vision:
        name = "fake_vision"
        calls = 0

        async def describe(self, photos):
            _Vision.calls += 1
            _Vision.last_photo_count = len(photos)
            return vision

    monkeypatch.setattr(settings, "recognition_mode", "vision_first")
    for module in (registry, recognition_service):
        monkeypatch.setattr(module, "get_ocr_provider", lambda: _Ocr())
        monkeypatch.setattr(module, "get_vision_provider", lambda: _Vision())
    return _Vision


async def _seed_catalog():
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка Common Rail", category="fuel_equipment", maker="BOSCH",
                 impa_code="350101", oem_number="0445120123"),
        ])


async def _make_scan(db, vessel_id, author_id, kinds):
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


async def _recognition(scan_id):
    from sqlalchemy import select
    from app.models.scan import Recognition
    async with SessionLocal() as db:
        return await db.scalar(select(Recognition).where(Recognition.scan_id == scan_id))


# ── Скан без шильдика доходит до отчёта ─────────────────────────────────────

async def test_scan_without_nameplate_reaches_report(data, stub_storage, monkeypatch):
    """Один кадр «общий вид» — конвейер обязан отработать и дать опознание."""
    _patch(monkeypatch, _by_appearance())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"],
                                   kinds=("overview",))
        outcome = await recognition_service.run_pipeline(db, scan_id)

    assert outcome.scan_status.value in ("done", "needs_review"), \
        "скан без шильдика обязан дойти до отчёта, а не упасть"
    assert outcome.confidence == 82, "доверие берётся от модели"

    rec = await _recognition(scan_id)
    assert rec is not None
    from app.services import report_service
    ident = report_service.extract_identification(rec)
    assert ident is not None, "опознание должно быть даже без таблички"
    assert ident["part_type"] == "насос центробежный"


async def test_all_frames_go_to_model_without_nameplate(data, stub_storage, monkeypatch):
    """Без шильдика в модель всё равно уходят все имеющиеся кадры."""
    fake_vision = _patch(monkeypatch, _by_appearance())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"],
                                   kinds=("overview", "context"))
        await recognition_service.run_pipeline(db, scan_id)

    assert fake_vision.calls == 1
    assert fake_vision.last_photo_count == 2, "оба кадра должны уйти в запрос"


# ── Опознание по виду не даёт точной закупки ────────────────────────────────

async def test_appearance_only_gives_no_exact_purchase(data, stub_storage, monkeypatch):
    """Номера нет — позиция каталога не назначается, значит закупки по артикулу нет."""
    await _seed_catalog()
    _patch(monkeypatch, _by_appearance())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"],
                                   kinds=("overview",))
        await recognition_service.run_pipeline(db, scan_id)

    rec = await _recognition(scan_id)
    assert rec.identification_basis == IdentificationBasis.appearance.value
    assert rec.part_id is None, \
        "без подтверждённого номера точная позиция каталога назначаться не должна"


# ── Поведение с номером не изменилось ───────────────────────────────────────

async def test_confirmed_number_keeps_exact_match(data, stub_storage, monkeypatch):
    """Номер подтверждён каталогом — прежний путь: позиция и точная закупка."""
    await _seed_catalog()
    _patch(monkeypatch, _with_number())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"],
                                   kinds=("nameplate",))
        outcome = await recognition_service.run_pipeline(db, scan_id)

    assert outcome.catalog_status == "matched"

    rec = await _recognition(scan_id)
    assert rec.identification_basis == IdentificationBasis.by_number.value
    assert rec.part_id is not None, "точное совпадение обязано дать позицию каталога"


async def test_number_on_body_counts_as_confirmed(data, stub_storage, monkeypatch):
    """Номер, выбитый на корпусе, равнозначен табличке: кадр — общий вид."""
    await _seed_catalog()
    _patch(monkeypatch, _with_number())

    async with SessionLocal() as db:
        scan_id = await _make_scan(db, data["vessel_a"], data["users"]["mech_a"],
                                   kinds=("overview",))
        await recognition_service.run_pipeline(db, scan_id)

    rec = await _recognition(scan_id)
    assert rec.identification_basis == IdentificationBasis.by_number.value, \
        "основание определяется номером, а не типом кадра"
    assert rec.part_id is not None
