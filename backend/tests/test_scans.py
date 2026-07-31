# -*- coding: utf-8 -*-
"""Приём сканов (A1): валидация, идемпотентность, доступ, подписанные ссылки."""
import io
import json
import uuid

import pytest

from app.services import storage
from tests.conftest import auth_headers

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Хранилище подменяем: тесты не должны требовать поднятого MinIO."""
    saved: dict[str, bytes] = {}

    async def _ensure():
        return None

    async def _put(key, content, content_type):
        saved[key] = content

    async def _presign(key, ttl=None):
        return f"https://minio.test/{key}?sig=demo"

    def _get(key):
        return saved[key]

    monkeypatch.setattr(storage, "ensure_bucket", _ensure)
    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "presigned_url", _presign)
    monkeypatch.setattr(storage, "get_object_sync", _get)
    return saved


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    """Не дёргаем Celery из тестов API."""
    from app.api.v1.endpoints import scans as scans_api
    monkeypatch.setattr(scans_api, "_enqueue", lambda scan_id: None)


def _files(count=1):
    return [("photos", (f"p{i}.png", io.BytesIO(PNG), "image/png")) for i in range(count)]


def _meta(vessel_id, client_key=None, geo=None):
    body = {"vessel_id": str(vessel_id)}
    if client_key:
        body["client_scan_id"] = client_key
    if geo:
        body["geo"] = geo
    return {"meta": json.dumps(body)}


async def test_create_scan_accepted(client, data):
    r = await client.post("/api/v1/scans", files=_files(2),
                          data=_meta(data["vessel_a"]),
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["idempotent_reuse"] is False


async def test_idempotent_by_client_scan_id(client, data, fake_storage):
    """Повторная отправка тем же ключом не создаёт дубль (NFR-REL-04)."""
    headers = await auth_headers(client, "mech_a")
    payload = _meta(data["vessel_a"], client_key="phone-abc-001")

    first = await client.post("/api/v1/scans", files=_files(1), data=payload, headers=headers)
    second = await client.post("/api/v1/scans", files=_files(1), data=payload, headers=headers)

    assert first.status_code == second.status_code == 202
    assert first.json()["scan_id"] == second.json()["scan_id"]
    assert second.json()["idempotent_reuse"] is True
    # и фото повторно в хранилище не поехали — это прямая экономия (NFR-COST-01)
    assert len(fake_storage) == 1


async def test_too_many_photos_rejected(client, data):
    r = await client.post("/api/v1/scans", files=_files(4),
                          data=_meta(data["vessel_a"]),
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 422
    assert "Не более" in r.json()["error"]["message"]


async def test_unsupported_mime_rejected(client, data):
    files = [("photos", ("virus.exe", io.BytesIO(b"MZ..."), "application/x-msdownload"))]
    r = await client.post("/api/v1/scans", files=files,
                          data=_meta(data["vessel_a"]),
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_oversized_photo_rejected(client, data, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_photo_size_mb", 0)     # всё больше нуля — велико
    r = await client.post("/api/v1/scans", files=_files(1),
                          data=_meta(data["vessel_a"]),
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 413


async def test_foreign_vessel_hidden(client, data):
    """Судно чужой организации -> 404 (NFR-SEC-03)."""
    r = await client.post("/api/v1/scans", files=_files(1),
                          data=_meta(data["vessel_b"]),
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 404


async def test_mechanic_cannot_scan_unassigned_vessel(client, data):
    """Механик привязан к «Балтике», «Нева» ему недоступна (FR-AUTH-03)."""
    r = await client.post("/api/v1/scans", files=_files(1),
                          data=_meta(data["vessel_a2"]),
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 404


async def test_expert_cannot_create_scan(client, data):
    r = await client.post("/api/v1/scans", files=_files(1),
                          data=_meta(data["vessel_a"]),
                          headers=await auth_headers(client, "expert_a"))
    assert r.status_code == 403


async def test_scan_photos_have_signed_urls(client, data):
    """Прямого доступа к бакету нет — только временные ссылки (NFR-SEC-04)."""
    headers = await auth_headers(client, "mech_a")
    scan_id = (await client.post("/api/v1/scans", files=_files(2),
                                 data=_meta(data["vessel_a"]), headers=headers)).json()["scan_id"]

    r = await client.get(f"/api/v1/scans/{scan_id}", headers=headers)
    assert r.status_code == 200
    photos = r.json()["photos"]
    assert len(photos) == 2
    assert all(p["url"].startswith("https://minio.test/") and "sig=" in p["url"] for p in photos)
    # ключ в хранилище наружу не отдаём
    assert all("storage_key" not in p for p in photos)


async def test_photo_kinds_default_order(client, data):
    """По умолчанию: общий вид, шильдик, место установки (FR-CAP-01)."""
    headers = await auth_headers(client, "mech_a")
    scan_id = (await client.post("/api/v1/scans", files=_files(3),
                                 data=_meta(data["vessel_a"]), headers=headers)).json()["scan_id"]
    photos = (await client.get(f"/api/v1/scans/{scan_id}", headers=headers)).json()["photos"]
    assert [p["kind"] for p in photos] == ["overview", "nameplate", "context"]


async def test_other_org_cannot_read_scan(client, data):
    headers = await auth_headers(client, "mech_a")
    scan_id = (await client.post("/api/v1/scans", files=_files(1),
                                 data=_meta(data["vessel_a"]), headers=headers)).json()["scan_id"]

    r = await client.get(f"/api/v1/scans/{scan_id}",
                         headers=await auth_headers(client, "admin_b"))
    assert r.status_code == 404


async def test_report_before_recognition(client, data):
    headers = await auth_headers(client, "mech_a")
    scan_id = (await client.post("/api/v1/scans", files=_files(1),
                                 data=_meta(data["vessel_a"]), headers=headers)).json()["scan_id"]
    r = await client.get(f"/api/v1/scans/{scan_id}/report", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["recognition"] is None


async def test_retry_only_for_failed(client, data):
    headers = await auth_headers(client, "mech_a")
    scan_id = (await client.post("/api/v1/scans", files=_files(1),
                                 data=_meta(data["vessel_a"]), headers=headers)).json()["scan_id"]
    # queued -> переобработка допустима
    assert (await client.post(f"/api/v1/scans/{scan_id}/retry", headers=headers)).status_code == 202


async def test_bad_meta_json(client, data):
    r = await client.post("/api/v1/scans", files=_files(1),
                          data={"meta": "не json"},
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_unknown_vessel(client, data):
    r = await client.post("/api/v1/scans", files=_files(1),
                          data=_meta(uuid.uuid4()),
                          headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 404
