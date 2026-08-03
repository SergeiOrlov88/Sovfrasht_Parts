# -*- coding: utf-8 -*-
"""Панель эксперта (F2, FR-HITL-02/03/04) и уведомления (FR-NOT-01)."""
import io
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.catalog import Part
from app.models.enums import RecognitionStatus, ScanStatus
from app.models.notification import Notification
from app.models.scan import ModerationTask, Recognition, Scan, TrainingSample
from app.services import catalog_import, storage
from tests.conftest import auth_headers

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    saved: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "ensure_bucket", lambda: _noop())
    monkeypatch.setattr(storage, "put_object", lambda k, c, t: _save(saved, k, c))
    monkeypatch.setattr(storage, "presigned_url", lambda k, ttl=None: _url(k))
    monkeypatch.setattr(storage, "get_object_sync", lambda k: saved.get(k, PNG))


async def _noop():
    return None


async def _save(store, key, content):
    store[key] = content


async def _url(key):
    return f"https://minio.test/{key}?sig=demo"


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    from app.api.v1.endpoints import scans as scans_api
    monkeypatch.setattr(scans_api, "_enqueue", lambda scan_id: None)


async def _catalog():
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка Bosch", category="fuel_equipment", maker="Bosch",
                 oem_number="0445120100", equipment="Дизель CR",
                 specs='{"subtype":"cr_injector"}'),
            dict(name="Форсунка Denso", category="fuel_equipment", maker="Denso",
                 oem_number="095000-6353", equipment="Isuzu 4HK1",
                 specs='{"subtype":"cr_injector"}'),
        ])
    async with SessionLocal() as db:
        return (await db.scalar(select(Part).where(Part.oem_number_norm == "0445120100")),
                await db.scalar(select(Part).where(Part.oem_number_norm == "0950006353")))


async def _scan_needing_expert(client, data, part=None, confidence=42):
    """Скан с низким confidence и задачей эксперту."""
    headers = await auth_headers(client, "mech_a")
    files = [("photos", ("nameplate.png", io.BytesIO(PNG), "image/png"))]
    body = {"meta": json.dumps({"vessel_id": str(data["vessel_a"])})}
    scan_id = uuid.UUID((await client.post("/api/v1/scans", files=files, data=body,
                                           headers=headers)).json()["scan_id"])
    async with SessionLocal() as db:
        scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
        scan.status = ScanStatus.needs_review.value
        rec = Recognition(scan_id=scan_id, part_id=part.id if part else None,
                          confidence=confidence, ocr_text="BOSCH ...",
                          status=RecognitionStatus.auto.value, catalog_status="candidates")
        db.add(rec)
        await db.flush()
        db.add(ModerationTask(recognition_id=rec.id, status="pending"))
        await db.commit()
        task = await db.scalar(select(ModerationTask))
        return scan_id, task.id, headers


# ── RBAC (проверка на сервере, не только в UI) ───────────────────────────────

@pytest.mark.parametrize("who,expected", [
    ("expert_a", 200), ("admin_a", 200),
    ("mech_a", 403), ("supply_a", 403), ("owner_a", 403),
])
async def test_queue_access_by_role(client, data, who, expected):
    r = await client.get("/api/v1/moderation/tasks", headers=await auth_headers(client, who))
    assert r.status_code == expected


async def test_resolve_forbidden_for_mechanic(client, data):
    part, _ = await _catalog()
    _, task_id, headers = await _scan_needing_expert(client, data, part)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "confirmed"}, headers=headers)
    assert r.status_code == 403


async def test_queue_requires_auth(client, data):
    assert (await client.get("/api/v1/moderation/tasks")).status_code == 401


# ── Очередь (FR-HITL-02) ─────────────────────────────────────────────────────

async def test_queue_shows_everything_expert_needs(client, data):
    part, _ = await _catalog()
    scan_id, task_id, _ = await _scan_needing_expert(client, data, part)

    r = await client.get("/api/v1/moderation/tasks",
                         headers=await auth_headers(client, "expert_a"))
    assert r.json()["total"] == 1
    item = r.json()["items"][0]
    assert item["status"] == "pending"
    assert item["scan_id"] == str(scan_id)
    assert item["vessel_name"] == "Балтика"
    assert item["author_name"] == "mech_a"
    assert item["part"]["name"] == "Форсунка Bosch"       # предложенный результат
    assert item["recognition"]["confidence"] == 42
    assert item["photos"][0]["url"].startswith("https://minio.test/")   # NFR-SEC-04


async def test_queue_filters_by_status(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    expert = await auth_headers(client, "expert_a")

    await client.post(f"/api/v1/moderation/tasks/{task_id}/claim", headers=expert)
    assert (await client.get("/api/v1/moderation/tasks?status=pending",
                             headers=expert)).json()["total"] == 0
    assert (await client.get("/api/v1/moderation/tasks?status=in_progress",
                             headers=expert)).json()["total"] == 1


# ── Взятие в работу ──────────────────────────────────────────────────────────

async def test_claim_sets_expert_and_status(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/claim",
                          headers=await auth_headers(client, "expert_a"))
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"
    assert r.json()["expert_id"] == str(data["users"]["expert_a"])
    assert r.json()["claimed_at"] is not None


async def test_claim_twice_by_same_expert_is_safe(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    expert = await auth_headers(client, "expert_a")
    await client.post(f"/api/v1/moderation/tasks/{task_id}/claim", headers=expert)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/claim", headers=expert)
    assert r.status_code == 200


async def test_claimed_task_not_stolen_by_other_expert(client, data):
    """Два эксперта не должны делать одну работу."""
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    await client.post(f"/api/v1/moderation/tasks/{task_id}/claim",
                      headers=await auth_headers(client, "expert_a"))
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/claim",
                          headers=await auth_headers(client, "admin_a"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "already_claimed"


# ── Решение (FR-HITL-03) ─────────────────────────────────────────────────────

async def test_corrected_updates_recognition_and_creates_sample(client, data):
    bosch, denso = await _catalog()
    scan_id, task_id, _ = await _scan_needing_expert(client, data, bosch)
    expert = await auth_headers(client, "expert_a")

    await client.post(f"/api/v1/moderation/tasks/{task_id}/claim", headers=expert)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "corrected",
                                "correct_part_id": str(denso.id)}, headers=expert)
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"
    assert r.json()["resolution"] == "corrected"
    assert r.json()["part"]["maker"] == "Denso"

    async with SessionLocal() as db:
        rec = await db.scalar(select(Recognition))
        assert rec.part_id == denso.id
        assert rec.status == "corrected"
        scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan.status == ScanStatus.done.value      # разблокировано
        sample = await db.scalar(select(TrainingSample))
        assert sample.correct_part_id == denso.id
        assert sample.source == "expert"                 # решение эксперта ценнее


async def test_corrected_requires_part(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "corrected"},
                          headers=await auth_headers(client, "expert_a"))
    assert r.status_code == 422


async def test_confirmed_marks_recognition(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "confirmed"},
                          headers=await auth_headers(client, "expert_a"))
    assert r.json()["resolution"] == "confirmed"
    async with SessionLocal() as db:
        assert (await db.scalar(select(Recognition))).status == "confirmed"


async def test_confirm_without_part_rejected(client, data):
    await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part=None)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "confirmed"},
                          headers=await auth_headers(client, "expert_a"))
    assert r.status_code == 422


async def test_rejected_marks_scan_error(client, data):
    part, _ = await _catalog()
    scan_id, task_id, _ = await _scan_needing_expert(client, data, part)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "rejected"},
                          headers=await auth_headers(client, "expert_a"))
    assert r.json()["resolution"] == "rejected"
    async with SessionLocal() as db:
        assert (await db.scalar(select(Scan).where(Scan.id == scan_id))).status == "error"
        # Верная деталь неизвестна — обучающего примера нет
        assert await db.scalar(select(func.count()).select_from(TrainingSample)) == 0


async def test_resolve_twice_conflicts(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    expert = await auth_headers(client, "expert_a")
    await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                      json={"resolution": "confirmed"}, headers=expert)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "confirmed"}, headers=expert)
    assert r.status_code == 409


async def test_unknown_correct_part(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "corrected",
                                "correct_part_id": str(uuid.uuid4())},
                          headers=await auth_headers(client, "expert_a"))
    assert r.status_code == 404


# ── Разблокировка downstream ─────────────────────────────────────────────────

async def test_expert_decision_unblocks_purchase(client, data):
    """Ключевое: после исправления экспертом автор может оформить заявку,
    хотя confidence остался низким (FR-REC-04 + FR-HITL-03)."""
    bosch, denso = await _catalog()
    scan_id, task_id, mech = await _scan_needing_expert(client, data, bosch, confidence=42)

    async with SessionLocal() as db:
        rec_id = (await db.scalar(select(Recognition))).id

    # До решения эксперта — заявка блокируется порогом
    blocked = await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
        "recognition_id": str(rec_id)}, headers=mech)
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "confidence_too_low"

    await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                      json={"resolution": "corrected", "correct_part_id": str(denso.id)},
                      headers=await auth_headers(client, "expert_a"))

    # После — проходит, потому что результат подтверждён человеком
    ok = await client.post("/api/v1/part-requests", json={
        "part_id": str(denso.id), "vessel_id": str(data["vessel_a"]),
        "recognition_id": str(rec_id)}, headers=mech)
    assert ok.status_code == 201


async def test_author_sees_updated_report(client, data):
    bosch, denso = await _catalog()
    scan_id, task_id, mech = await _scan_needing_expert(client, data, bosch)
    await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                      json={"resolution": "corrected", "correct_part_id": str(denso.id)},
                      headers=await auth_headers(client, "expert_a"))

    report = (await client.get(f"/api/v1/scans/{scan_id}/report", headers=mech)).json()
    assert report["part"]["maker"] == "Denso"
    assert report["status"] == "done"
    assert report["recognition"]["status"] == "corrected"


# ── Уведомления (FR-NOT-01) ──────────────────────────────────────────────────

async def test_author_notified_about_decision(client, data):
    bosch, denso = await _catalog()
    _, task_id, mech = await _scan_needing_expert(client, data, bosch)
    await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                      json={"resolution": "corrected", "correct_part_id": str(denso.id)},
                      headers=await auth_headers(client, "expert_a"))

    r = await client.get("/api/v1/notifications", headers=mech)
    body = r.json()
    assert body["unread"] == 1
    note = body["items"][0]
    assert note["type"] == "expert_resolved"
    assert "Форсунка Denso" in note["body"]
    assert note["payload"]["resolution"] == "corrected"


async def test_notification_marked_read(client, data):
    bosch, _ = await _catalog()
    _, task_id, mech = await _scan_needing_expert(client, data, bosch)
    await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                      json={"resolution": "confirmed"},
                      headers=await auth_headers(client, "expert_a"))

    note_id = (await client.get("/api/v1/notifications", headers=mech)).json()["items"][0]["id"]
    r = await client.post(f"/api/v1/notifications/{note_id}/read", headers=mech)
    assert r.json()["read_at"] is not None
    assert (await client.get("/api/v1/notifications", headers=mech)).json()["unread"] == 0


async def test_notifications_are_private(client, data):
    """Чужие уведомления не видны и не помечаются прочитанными."""
    bosch, _ = await _catalog()
    _, task_id, mech = await _scan_needing_expert(client, data, bosch)
    await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                      json={"resolution": "confirmed"},
                      headers=await auth_headers(client, "expert_a"))

    note_id = (await client.get("/api/v1/notifications", headers=mech)).json()["items"][0]["id"]
    other = await auth_headers(client, "supply_a")
    assert (await client.get("/api/v1/notifications", headers=other)).json()["total"] == 0
    assert (await client.post(f"/api/v1/notifications/{note_id}/read",
                              headers=other)).status_code == 404


# ── SLA (FR-HITL-04) ─────────────────────────────────────────────────────────

async def test_sla_recorded(client, data):
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    expert = await auth_headers(client, "expert_a")
    await client.post(f"/api/v1/moderation/tasks/{task_id}/claim", headers=expert)
    r = await client.post(f"/api/v1/moderation/tasks/{task_id}/resolve",
                          json={"resolution": "confirmed"}, headers=expert)
    sla = r.json()["sla"]
    assert sla["wait_seconds"] is not None
    assert sla["work_seconds"] is not None
    assert sla["total_seconds"] is not None
    assert sla["total_seconds"] >= sla["work_seconds"]


async def test_sla_wait_counts_for_pending_task(client, data):
    """У невзятой задачи время ожидания идёт, а время работы ещё не определено."""
    part, _ = await _catalog()
    _, task_id, _ = await _scan_needing_expert(client, data, part)
    r = await client.get(f"/api/v1/moderation/tasks/{task_id}",
                         headers=await auth_headers(client, "expert_a"))
    sla = r.json()["sla"]
    assert sla["wait_seconds"] is not None
    assert sla["work_seconds"] is None and sla["total_seconds"] is None
