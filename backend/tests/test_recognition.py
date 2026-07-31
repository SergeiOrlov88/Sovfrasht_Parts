# -*- coding: utf-8 -*-
"""Конвейер распознавания (A2): OCR-ветка, fallback, порог, кэш, отказ провайдера."""
import uuid

import pytest
from sqlalchemy import func, select

from app.adapters.vision import registry
from app.adapters.vision.base import OcrResult, ProviderUnavailable, VisionResult
from app.adapters.vision.vision_llm import parse_vision_reply
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.enums import ScanStatus
from app.models.scan import ModerationTask, Photo, Recognition, Scan
from app.models.vision_cache import VisionCache
from app.services import catalog_import, recognition_service, storage


# ── Разбор ответов vision-модели ─────────────────────────────────────────────

@pytest.mark.parametrize("reply", [
    '{"category":"насос","description":"центробежный насос","maker":null,"confidence":40}',
    '```json\n{"category":"насос","description":"центробежный насос","confidence":40}\n```',
    'Вот ответ: {"category":"насос","description":"центробежный насос","confidence":40} — всё.',
])
def test_parse_vision_reply_tolerates_wrapping(reply):
    parsed = parse_vision_reply(reply)
    assert parsed["category"] == "насос"
    assert parsed["confidence"] == 40


def test_parse_vision_reply_on_garbage():
    assert parse_vision_reply("модель отказалась отвечать") == {}


# ── Оценка достоверности (FR-REC-03) ─────────────────────────────────────────

def test_score_full_nameplate_passes_threshold():
    score = recognition_service.score_ocr(OcrResult(
        text="MAKER BOSCH PART NO 0445120123 SERIAL 998877",
        maker="BOSCH", oem_number="0445120123", serial_number="998877",
    ))
    assert score >= settings.confidence_threshold


def test_score_text_without_number_below_threshold():
    score = recognition_service.score_ocr(OcrResult(text="какой-то нечитаемый текст с фото"))
    assert score < settings.confidence_threshold


def test_score_empty_is_zero():
    assert recognition_service.score_ocr(OcrResult()) == 0


# ── Конвейер целиком ─────────────────────────────────────────────────────────

@pytest.fixture
def stub_storage(monkeypatch):
    monkeypatch.setattr(storage, "get_object_sync", lambda key: b"\x89PNG\r\n\x1a\nbytes")


async def _seed_part(oem="0445120123", maker="BOSCH"):
    """Каталог нужен, потому что итоговый confidence зависит от результата матчинга."""
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка Common Rail", category="fuel_equipment",
                 maker=maker, oem_number=oem)])


async def _make_scan(data, kinds=("nameplate",)) -> uuid.UUID:
    async with SessionLocal() as db:
        scan = Scan(vessel_id=data["vessel_a"], author_id=data["users"]["mech_a"],
                    status=ScanStatus.queued.value)
        db.add(scan)
        await db.flush()
        for i, kind in enumerate(kinds):
            db.add(Photo(scan_id=scan.id, storage_key=f"k{i}", kind=kind,
                         mime_type="image/png", content_sha256=f"sha-{i}"))
        await db.commit()
        return scan.id


def _patch_providers(monkeypatch, ocr: OcrResult | Exception, vision: VisionResult | None = None):
    class _Ocr:
        name = "test_ocr"

        async def recognize_text(self, photo):
            if isinstance(ocr, Exception):
                raise ocr
            return ocr

    class _Vision:
        name = "test_vision"

        async def describe(self, photos):
            return vision or VisionResult()

    monkeypatch.setattr(registry, "get_ocr_provider", lambda: _Ocr())
    monkeypatch.setattr(registry, "get_vision_provider", lambda: _Vision())
    monkeypatch.setattr(recognition_service, "get_ocr_provider", lambda: _Ocr())
    monkeypatch.setattr(recognition_service, "get_vision_provider", lambda: _Vision())


async def test_readable_nameplate_goes_done(client, data, stub_storage, monkeypatch):
    """Шильдик прочитан -> высокий confidence -> done, эксперт не нужен."""
    _patch_providers(monkeypatch, OcrResult(
        text="MAKER BOSCH PART NO 0445120123 SERIAL 998877", maker="BOSCH",
        oem_number="0445120123", serial_number="998877", model_version="test_ocr:v1",
    ))
    await _seed_part()
    scan_id = await _make_scan(data)
    async with SessionLocal() as db:
        outcome = await recognition_service.run_pipeline(db, scan_id)

    assert outcome.catalog_status == "matched"
    assert outcome.scan_status is ScanStatus.done
    assert outcome.needs_expert is False
    assert outcome.used_fallback is False

    async with SessionLocal() as db:
        rec = await db.scalar(select(Recognition).where(Recognition.scan_id == scan_id))
        assert rec.oem_detected == "0445120123"
        assert rec.maker_detected == "BOSCH"
        assert rec.model_version == "test_ocr:v1"
        # задачи эксперту быть не должно
        assert await db.scalar(select(func.count()).select_from(ModerationTask)) == 0


async def test_unreadable_nameplate_falls_back_to_vision(client, data, stub_storage, monkeypatch):
    """Шильдик не читается -> vision-модель -> низкий confidence -> HITL."""
    _patch_providers(
        monkeypatch,
        OcrResult(text="..."),                       # нечитаемо
        VisionResult(description="центробежный насос", category="насосы",
                     confidence=40, model_version="test_vision:v1"),
    )
    scan_id = await _make_scan(data)
    async with SessionLocal() as db:
        outcome = await recognition_service.run_pipeline(db, scan_id)

    assert outcome.used_fallback is True
    assert outcome.scan_status is ScanStatus.needs_review
    assert outcome.needs_expert is True
    assert outcome.confidence == 20   # 40, понижено из-за not_found в каталоге

    async with SessionLocal() as db:
        rec = await db.scalar(select(Recognition).where(Recognition.scan_id == scan_id))
        assert rec.ocr_text == "центробежный насос"
        # создана задача эксперту (FR-REC-04, F1)
        task = await db.scalar(select(ModerationTask)
                               .where(ModerationTask.recognition_id == rec.id))
        assert task is not None and task.status == "pending"


async def test_moderation_task_not_duplicated_on_reprocess(client, data, stub_storage, monkeypatch):
    _patch_providers(monkeypatch, OcrResult(text="..."),
                     VisionResult(description="насос", confidence=30))
    scan_id = await _make_scan(data)
    async with SessionLocal() as db:
        await recognition_service.run_pipeline(db, scan_id)
    async with SessionLocal() as db:
        await recognition_service.run_pipeline(db, scan_id)
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(ModerationTask)) == 1


async def test_cache_prevents_second_paid_call(client, data, stub_storage, monkeypatch):
    """Повторная обработка того же фото не платит провайдеру дважды (NFR-COST-01)."""
    calls = {"n": 0}
    result = OcrResult(text="MAKER BOSCH PART NO 0445120123", maker="BOSCH",
                       oem_number="0445120123", model_version="test_ocr:v1")

    class _Ocr:
        name = "test_ocr"

        async def recognize_text(self, photo):
            calls["n"] += 1
            return result

    monkeypatch.setattr(recognition_service, "get_ocr_provider", lambda: _Ocr())
    monkeypatch.setattr(recognition_service, "get_vision_provider",
                        lambda: type("V", (), {"name": "v", "describe": None})())

    await _seed_part()
    scan_id = await _make_scan(data)
    async with SessionLocal() as db:
        first = await recognition_service.run_pipeline(db, scan_id)
    async with SessionLocal() as db:
        second = await recognition_service.run_pipeline(db, scan_id)

    assert calls["n"] == 1                    # второй раз ушли в кэш
    assert first.cache_hits == 0 and second.cache_hits == 1

    async with SessionLocal() as db:
        cached = await db.scalar(select(VisionCache))
        assert cached.hit_count == 1


async def test_cache_disabled_calls_provider_again(client, data, stub_storage, monkeypatch):
    monkeypatch.setattr(settings, "vision_cache_enabled", False)
    calls = {"n": 0}

    class _Ocr:
        name = "test_ocr"

        async def recognize_text(self, photo):
            calls["n"] += 1
            return OcrResult(text="MAKER BOSCH PART NO 0445120123", oem_number="0445120123")

    monkeypatch.setattr(recognition_service, "get_ocr_provider", lambda: _Ocr())
    scan_id = await _make_scan(data)
    async with SessionLocal() as db:
        await recognition_service.run_pipeline(db, scan_id)
    async with SessionLocal() as db:
        await recognition_service.run_pipeline(db, scan_id)
    assert calls["n"] == 2


async def test_provider_down_marks_error_and_scan_survives(client, data, stub_storage, monkeypatch):
    """Внешний сервис лежит -> скан не теряется, остаётся с ошибкой (NFR-REL-02/03)."""
    _patch_providers(monkeypatch, ProviderUnavailable("yandex недоступен"))
    scan_id = await _make_scan(data)

    async with SessionLocal() as db:
        with pytest.raises(ProviderUnavailable):
            await recognition_service.run_pipeline(db, scan_id)
        await recognition_service.mark_error(db, scan_id)

    async with SessionLocal() as db:
        scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan.status == ScanStatus.error.value


async def test_nameplate_photo_preferred_for_ocr(client, data, stub_storage, monkeypatch):
    """OCR идёт по кадру шильдика, а не по общему виду (FR-REC-02)."""
    seen: list[str] = []

    class _Ocr:
        name = "test_ocr"

        async def recognize_text(self, photo):
            seen.append(photo.kind)
            return OcrResult(text="PART NO 0445120123", oem_number="0445120123")

    monkeypatch.setattr(recognition_service, "get_ocr_provider", lambda: _Ocr())
    scan_id = await _make_scan(data, kinds=("overview", "nameplate", "context"))
    async with SessionLocal() as db:
        await recognition_service.run_pipeline(db, scan_id)

    assert seen == ["nameplate"]


async def test_stub_provider_degrades_to_expert(client, data, stub_storage, monkeypatch):
    """Провайдер не настроен -> не падаем, но результат уходит эксперту."""
    monkeypatch.setattr(settings, "ocr_provider", "stub")
    monkeypatch.setattr(settings, "vision_provider", "stub")
    scan_id = await _make_scan(data)
    async with SessionLocal() as db:
        outcome = await recognition_service.run_pipeline(db, scan_id)
    assert outcome.scan_status is ScanStatus.needs_review
    assert outcome.confidence == 0
