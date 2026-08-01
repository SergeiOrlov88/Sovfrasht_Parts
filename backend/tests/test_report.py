# -*- coding: utf-8 -*-
"""Отчёт (B1, FR-REP-01..03) и обратная связь (B3, FR-REP-04)."""
import io
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.catalog import Part
from app.models.enums import RecognitionStatus, ScanStatus
from app.models.scan import ModerationTask, Recognition, Scan, TrainingSample
from app.services import catalog_import, report_service, storage
from tests.conftest import auth_headers

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    saved: dict[str, bytes] = {}

    async def _ensure():
        return None

    async def _put(key, content, content_type):
        saved[key] = content

    async def _presign(key, ttl=None):
        return f"https://minio.test/{key}?sig=demo"

    monkeypatch.setattr(storage, "ensure_bucket", _ensure)
    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "presigned_url", _presign)
    monkeypatch.setattr(storage, "get_object_sync", lambda key: saved.get(key, PNG))


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    from app.api.v1.endpoints import scans as scans_api
    monkeypatch.setattr(scans_api, "_enqueue", lambda scan_id: None)


async def _catalog():
    """Каталог: деталь с аналогом (FR-REP-03)."""
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка Common Rail Bosch", category="fuel_equipment", maker="Bosch",
                 impa_code="350101", oem_number="0445120100",
                 equipment="Дизель Common Rail", specs='{"давление_бар":1800,"сопел":7}',
                 alt_oem="095000-6353"),
            dict(name="Форсунка Common Rail Denso", category="fuel_equipment", maker="Denso",
                 oem_number="095000-6353", equipment="Isuzu 4HK1"),
        ])
    async with SessionLocal() as db:
        return await db.scalar(select(Part).where(Part.oem_number_norm == "0445120100"))


async def _scan_with_recognition(client, data, *, part=None, confidence=85,
                                 catalog_status="matched"):
    """Скан с готовым результатом распознавания."""
    headers = await auth_headers(client, "mech_a")
    files = [("photos", ("n.png", io.BytesIO(PNG), "image/png"))]
    body = {"meta": json.dumps({"vessel_id": str(data["vessel_a"])})}
    scan_id = uuid.UUID((await client.post("/api/v1/scans", files=files, data=body,
                                           headers=headers)).json()["scan_id"])
    async with SessionLocal() as db:
        scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
        scan.status = ScanStatus.done.value if confidence >= settings.confidence_threshold \
            else ScanStatus.needs_review.value
        db.add(Recognition(
            scan_id=scan.id, part_id=part.id if part else None, confidence=confidence,
            ocr_text="BOSCH PART NO 0445120100", maker_detected="Bosch",
            oem_detected="0445120100" if part else None,
            model_version="test:v1", status=RecognitionStatus.auto.value,
            catalog_status=catalog_status,
        ))
        await db.commit()
    return scan_id, headers


# ── Полнота отчёта (FR-REP-01) ───────────────────────────────────────────────

async def test_report_contains_all_required_fields(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)

    body = (await client.get(f"/api/v1/scans/{scan_id}/report", headers=headers)).json()
    p = body["part"]
    assert p["name"] == "Форсунка Common Rail Bosch"
    assert p["equipment"] == "Дизель Common Rail"
    assert p["impa_code"] == "350101"
    assert p["oem_number"] == "0445120100"
    assert p["maker"] == "Bosch"
    assert p["specs"]["давление_бар"] == 1800
    assert body["confidence"] == 85
    assert body["created_at"]


async def test_report_shows_alternatives(client, data):
    """FR-REP-03: аналоги из PartAlternative."""
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)
    body = (await client.get(f"/api/v1/scans/{scan_id}/report", headers=headers)).json()
    assert len(body["alternatives"]) == 1
    assert body["alternatives"][0]["part"]["maker"] == "Denso"
    assert body["alternatives"][0]["compatibility"] == "full"


# ── Индикатор достоверности (FR-REP-02) ──────────────────────────────────────

@pytest.mark.parametrize("confidence,level", [(95, "high"), (72, "medium"), (40, "low")])
def test_confidence_level(confidence, level):
    assert report_service.confidence_level(confidence) == level


async def test_high_confidence_has_no_warning(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part, confidence=95)
    body = (await client.get(f"/api/v1/scans/{scan_id}/report", headers=headers)).json()
    assert body["confidence_level"] == "high"
    assert body["warning"] is None
    assert body["needs_expert"] is False
    assert body["can_confirm"] is True


async def test_low_confidence_warns_and_offers_expert(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part, confidence=40)
    body = (await client.get(f"/api/v1/scans/{scan_id}/report", headers=headers)).json()
    assert body["confidence_level"] == "low"
    assert "ниже порога" in body["warning"]
    assert body["needs_expert"] is True
    assert body["can_request_expert"] is True


async def test_not_found_report_is_honest(client, data):
    """Детали нет в каталоге — говорим прямо, подтверждать нечего."""
    scan_id, headers = await _scan_with_recognition(
        client, data, part=None, confidence=20, catalog_status="not_found")
    body = (await client.get(f"/api/v1/scans/{scan_id}/report", headers=headers)).json()
    assert body["part"] is None
    assert body["candidates"] == []
    assert "нет в каталоге" in body["warning"]
    assert body["can_confirm"] is False           # подтверждать нечего
    assert body["can_request_expert"] is True


# ── Обратная связь (FR-REP-04, B3) ───────────────────────────────────────────

async def test_confirm_marks_recognition_and_creates_training_sample(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)

    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "confirm"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recognition_status"] == "confirmed"
    assert body["training_sample_created"] is True

    async with SessionLocal() as db:
        sample = await db.scalar(select(TrainingSample))
        assert sample.correct_part_id == part.id
        assert sample.source == "user_feedback"
        assert sample.photo_id is not None          # привязан кадр шильдика


async def test_reject_with_correction_updates_part(client, data):
    part = await _catalog()
    async with SessionLocal() as db:
        other = await db.scalar(select(Part).where(Part.oem_number_norm == "0950006353"))
    scan_id, headers = await _scan_with_recognition(client, data, part=part)

    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "reject", "correct_part_id": str(other.id)},
                          headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["recognition_status"] == "corrected"
    assert body["part"]["maker"] == "Denso"
    assert body["training_sample_created"] is True
    assert body["moderation_task_created"] is False   # правильная деталь известна

    async with SessionLocal() as db:
        rec = await db.scalar(select(Recognition))
        assert rec.part_id == other.id


async def test_reject_without_correction_goes_to_expert(client, data):
    """Пользователь сказал «не то», но что верно — не знает: это к эксперту (F1)."""
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)

    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "reject"}, headers=headers)
    body = r.json()
    assert body["recognition_status"] == "rejected"
    assert body["moderation_task_created"] is True
    assert body["training_sample_created"] is False   # верная деталь неизвестна

    async with SessionLocal() as db:
        scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan.status == ScanStatus.needs_review.value
        assert await db.scalar(select(func.count()).select_from(ModerationTask)) == 1


async def test_confirm_impossible_without_part(client, data):
    scan_id, headers = await _scan_with_recognition(
        client, data, part=None, confidence=20, catalog_status="not_found")
    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "confirm"}, headers=headers)
    assert r.status_code == 422
    assert "не определена" in r.json()["error"]["message"]


async def test_confirm_with_correct_part_on_not_found(client, data):
    """Деталь не нашлась, но пользователь знает верную позицию — принимаем."""
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(
        client, data, part=None, confidence=20, catalog_status="not_found")
    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "confirm", "correct_part_id": str(part.id)},
                          headers=headers)
    assert r.status_code == 200
    assert r.json()["recognition_status"] == "corrected"


async def test_feedback_recorded_in_report(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)
    await client.post(f"/api/v1/scans/{scan_id}/feedback",
                      json={"verdict": "confirm", "comment": "всё верно"}, headers=headers)

    body = (await client.get(f"/api/v1/scans/{scan_id}/report", headers=headers)).json()
    assert body["feedback"]["verdict"] == "confirm"
    assert body["can_confirm"] is False        # повторно подтверждать нечего
    async with SessionLocal() as db:
        rec = await db.scalar(select(Recognition))
        assert rec.feedback_comment == "всё верно"
        assert rec.feedback_by == data["users"]["mech_a"]


async def test_training_sample_not_duplicated(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)
    for _ in range(2):
        await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "confirm"}, headers=headers)
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TrainingSample)) == 1


async def test_unknown_correct_part_rejected(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)
    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "reject", "correct_part_id": str(uuid.uuid4())},
                          headers=headers)
    assert r.status_code == 404


async def test_feedback_before_recognition_conflicts(client, data):
    headers = await auth_headers(client, "mech_a")
    files = [("photos", ("n.png", io.BytesIO(PNG), "image/png"))]
    body = {"meta": json.dumps({"vessel_id": str(data["vessel_a"])})}
    scan_id = (await client.post("/api/v1/scans", files=files, data=body,
                                 headers=headers)).json()["scan_id"]
    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "confirm"}, headers=headers)
    assert r.status_code == 409


async def test_invalid_verdict_rejected(client, data):
    part = await _catalog()
    scan_id, headers = await _scan_with_recognition(client, data, part=part)
    r = await client.post(f"/api/v1/scans/{scan_id}/feedback",
                          json={"verdict": "maybe"}, headers=headers)
    assert r.status_code == 422


async def test_foreign_org_cannot_send_feedback(client, data):
    part = await _catalog()
    scan_id, _ = await _scan_with_recognition(client, data, part=part)
    r = await client.post(f"/api/v1/scans/{scan_id}/feedback", json={"verdict": "confirm"},
                          headers=await auth_headers(client, "admin_b"))
    assert r.status_code == 404
