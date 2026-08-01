# -*- coding: utf-8 -*-
"""Закупка: предложения поставщиков (C1) и заявки на снабжение (C2)."""
import uuid

import pytest
from sqlalchemy import func, select

from app.adapters.suppliers.base import Offer, SupplierInfo, SupplierProvider, SupplierUnavailable
from app.adapters.suppliers.curated import CuratedProvider
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.catalog import Part, Supplier, SupplierOffer
from app.models.enums import RecognitionStatus, ScanStatus
from app.models.scan import PartRequest, Recognition, Scan
from app.services import catalog_import, offers_import, purchase_service
from tests.conftest import auth_headers


async def _catalog_with_offers():
    """Каталог из двух деталей-аналогов и предложения к ним."""
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка Common Rail Bosch", category="fuel_equipment", maker="Bosch",
                 oem_number="0445120100", equipment="Дизель Common Rail",
                 alt_oem="51101006127"),
            dict(name="Форсунка Common Rail MAN", category="fuel_equipment", maker="MAN",
                 oem_number="51101006127", equipment="MAN D2676"),
        ])
    async with SessionLocal() as db:
        await offers_import.import_offers(db, [
            dict(part_oem="0445120100", supplier_name="ShipServ Pages", supplier_type="площадка",
                 supplier_region="Global", supplier_url="https://shipserv.com",
                 price="$1 190", lead_time="7–10 дн", stock_status="in",
                 deep_link="https://shipserv.com/p/0445120100"),
            dict(part_oem="0445120100", supplier_name="ReMarine", supplier_type="восстановление",
                 price="$690", lead_time="5–8 дн", stock_status="low",
                 deep_link="https://remarine.example/690"),
            dict(part_oem="51101006127", supplier_name="MAN Genuine Parts", supplier_type="OEM",
                 price="$1 260", lead_time="7–12 дн", stock_status="in"),
        ])
    async with SessionLocal() as db:
        bosch = await db.scalar(select(Part).where(Part.oem_number_norm == "0445120100"))
        man = await db.scalar(select(Part).where(Part.oem_number_norm == "51101006127"))
        return bosch, man


# ── Загрузчик предложений ────────────────────────────────────────────────────

async def test_offers_import_creates_suppliers_and_marks_source(client, data):
    await _catalog_with_offers()
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(Supplier)) == 3
        offer = await db.scalar(select(SupplierOffer))
        # Демо-цены обязаны быть отличимы от полученных по API (ADR-05)
        assert offer.source == "demo"
        assert offer.fetched_at is not None


async def test_offers_import_maps_russian_supplier_types(client, data):
    await _catalog_with_offers()
    async with SessionLocal() as db:
        by_name = {s.name: s.type for s in (await db.scalars(select(Supplier))).all()}
    assert by_name["ShipServ Pages"] == "marketplace"
    assert by_name["ReMarine"] == "reman"          # «восстановление» — отдельный тип
    assert by_name["MAN Genuine Parts"] == "oem"


async def test_offers_import_is_idempotent(client, data):
    await _catalog_with_offers()
    async with SessionLocal() as db:
        report = await offers_import.import_offers(db, [
            dict(part_oem="0445120100", supplier_name="ShipServ Pages",
                 supplier_type="площадка", price="$1 210", stock_status="in"),
        ])
    assert report.offers_created == 0 and report.offers_updated == 1
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SupplierOffer)) == 3


async def test_offers_import_rejects_unknown_part(client, data):
    async with SessionLocal() as db:
        report = await offers_import.import_offers(db, [
            dict(part_oem="НЕТ-ТАКОГО", supplier_name="X", supplier_type="площадка")])
    assert report.skipped == 1
    assert "не найдена в каталоге" in report.errors[0]


# ── Адаптер поставщика (ADR-05) ──────────────────────────────────────────────

async def test_curated_provider_sorts_in_stock_and_cheap_first(client, data):
    bosch, _ = await _catalog_with_offers()
    async with SessionLocal() as db:
        offers = await CuratedProvider(db).get_offers(bosch)
    # «in» раньше «low», внутри — дешевле раньше
    assert [o.stock_status for o in offers] == ["in", "low"]


async def test_provider_swappable_without_touching_service(client, data):
    """Ядро не знает, откуда предложения: подменяем провайдера — сервис тот же."""
    bosch, _ = await _catalog_with_offers()

    class FakeApiProvider(SupplierProvider):
        name = "api"

        async def get_offers(self, part):
            return [Offer(supplier=SupplierInfo(name="API поставщик", type="oem"),
                          price="$999", stock_status="in", source="api")]

    async with SessionLocal() as db:
        offers = await purchase_service.offers_for_part(db, bosch, provider=FakeApiProvider())
    assert offers[0].source == "api"
    assert offers[0].supplier.name == "API поставщик"


async def test_offers_endpoint_includes_alternative(client, data):
    """Аналог MAN показывается рядом с оригиналом Bosch (FR-PRO-02)."""
    bosch, man = await _catalog_with_offers()
    r = await client.get(f"/api/v1/parts/{bosch.id}/offers",
                         headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 200
    body = r.json()
    assert len(body["offers"]) == 2
    assert body["offers"][0]["supplier"]["name"] == "ShipServ Pages"
    assert body["offers"][0]["deep_link"].startswith("https://")
    assert body["offers"][0]["source"] == "demo"
    assert len(body["alternatives"]) == 1
    assert body["alternatives"][0]["part"]["maker"] == "MAN"
    assert body["alternatives"][0]["offers"][0]["price"] == "$1 260"


async def test_offers_endpoint_without_alternatives(client, data):
    bosch, _ = await _catalog_with_offers()
    r = await client.get(f"/api/v1/parts/{bosch.id}/offers?with_alternatives=false",
                         headers=await auth_headers(client, "mech_a"))
    assert r.json()["alternatives"] == []


async def test_offers_for_part_without_offers(client, data):
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Деталь без предложений", maker="X", oem_number="XX00011")])
        part = await db.scalar(select(Part).where(Part.oem_number_norm == "XX00011"))
    r = await client.get(f"/api/v1/parts/{part.id}/offers",
                         headers=await auth_headers(client, "mech_a"))
    assert r.json()["offers"] == []
    assert "пока нет" in r.json()["message"]


async def test_offers_unknown_part(client, data):
    r = await client.get(f"/api/v1/parts/{uuid.uuid4()}/offers",
                         headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 404


async def test_supplier_unavailable_degrades_gracefully(client, data, monkeypatch):
    """Источник лёг — вкладка «Закупка» не роняет отчёт (NFR-REL-03)."""
    bosch, _ = await _catalog_with_offers()

    class DeadProvider(SupplierProvider):
        name = "dead"

        async def get_offers(self, part):
            raise SupplierUnavailable("источник недоступен")

    from app.adapters.suppliers import registry
    monkeypatch.setattr(registry, "get_supplier_provider", lambda db: DeadProvider())
    monkeypatch.setattr(purchase_service, "get_supplier_provider", lambda db: DeadProvider())

    r = await client.get(f"/api/v1/parts/{bosch.id}/offers",
                         headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 200
    assert r.json()["offers"] == []
    assert "временно недоступны" in r.json()["message"]


# ── Заявки (C2) ──────────────────────────────────────────────────────────────

async def _recognition(scan_status, confidence, rec_status=RecognitionStatus.auto):
    async with SessionLocal() as db:
        return None


async def _make_recognition(data, part, confidence, rec_status=RecognitionStatus.auto):
    async with SessionLocal() as db:
        scan = Scan(vessel_id=data["vessel_a"], author_id=data["users"]["mech_a"],
                    status=ScanStatus.done.value)
        db.add(scan)
        await db.flush()
        rec = Recognition(scan_id=scan.id, part_id=part.id, confidence=confidence,
                          status=rec_status.value, catalog_status="matched")
        db.add(rec)
        await db.commit()
        return rec.id


async def test_create_request(client, data):
    bosch, _ = await _catalog_with_offers()
    r = await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
        "quantity": 2, "priority": "urgent", "comment": "срочно на борт",
    }, headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "new"
    assert body["quantity"] == 2
    assert body["part"]["oem_number"] == "0445120100"
    assert body["vessel_name"] == "Балтика"
    assert body["next_statuses"] == ["in_review", "rejected"]


async def test_request_idempotent_by_client_key(client, data):
    """Повторная отправка тем же ключом не создаёт дубль (NFR-REL-04)."""
    bosch, _ = await _catalog_with_offers()
    payload = {"part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
               "client_request_id": "req-001"}
    headers = await auth_headers(client, "mech_a")

    first = await client.post("/api/v1/part-requests", json=payload, headers=headers)
    second = await client.post("/api/v1/part-requests", json=payload, headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["idempotent_reuse"] is True

    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(PartRequest)) == 1


async def test_low_confidence_blocks_request(client, data):
    """Ниже порога заявка не оформляется (FR-REC-04, NFR-ACC-03)."""
    bosch, _ = await _catalog_with_offers()
    rec_id = await _make_recognition(data, bosch, confidence=40)

    r = await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
        "recognition_id": str(rec_id),
    }, headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "confidence_too_low"
    assert body["details"]["threshold"] == settings.confidence_threshold


async def test_low_confidence_allowed_after_confirmation(client, data):
    """Человек подтвердил результат — заявку оформить можно."""
    bosch, _ = await _catalog_with_offers()
    rec_id = await _make_recognition(data, bosch, confidence=40,
                                     rec_status=RecognitionStatus.confirmed)
    r = await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
        "recognition_id": str(rec_id),
    }, headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 201


async def test_high_confidence_request_passes(client, data):
    bosch, _ = await _catalog_with_offers()
    rec_id = await _make_recognition(data, bosch, confidence=88)
    r = await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
        "recognition_id": str(rec_id),
    }, headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 201


async def test_request_for_foreign_vessel_hidden(client, data):
    bosch, _ = await _catalog_with_offers()
    r = await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_b"]),
    }, headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 404


async def test_expert_cannot_create_request(client, data):
    bosch, _ = await _catalog_with_offers()
    r = await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
    }, headers=await auth_headers(client, "expert_a"))
    assert r.status_code == 403


# ── Маршрут статусов (FR-PRO-04) ─────────────────────────────────────────────

async def test_status_flow_full_path(client, data):
    bosch, _ = await _catalog_with_offers()
    rid = (await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
    }, headers=await auth_headers(client, "mech_a"))).json()["id"]

    supply = await auth_headers(client, "supply_a")
    for status in ("in_review", "approved", "ordered", "received"):
        r = await client.patch(f"/api/v1/part-requests/{rid}",
                               json={"status": status}, headers=supply)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status
    assert r.json()["next_statuses"] == []          # received — конечный


async def test_invalid_transition_rejected(client, data):
    bosch, _ = await _catalog_with_offers()
    rid = (await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
    }, headers=await auth_headers(client, "mech_a"))).json()["id"]

    r = await client.patch(f"/api/v1/part-requests/{rid}", json={"status": "received"},
                           headers=await auth_headers(client, "supply_a"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_transition"
    assert r.json()["error"]["details"]["allowed"] == ["in_review", "rejected"]


async def test_mechanic_cannot_change_status(client, data):
    bosch, _ = await _catalog_with_offers()
    headers = await auth_headers(client, "mech_a")
    rid = (await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
    }, headers=headers)).json()["id"]

    r = await client.patch(f"/api/v1/part-requests/{rid}", json={"status": "in_review"},
                           headers=headers)
    assert r.status_code == 403


# ── Реестр (FR-PRO-04) ───────────────────────────────────────────────────────

async def test_registry_lists_and_filters(client, data):
    bosch, man = await _catalog_with_offers()
    headers = await auth_headers(client, "mech_a")
    for part in (bosch, man):
        await client.post("/api/v1/part-requests", json={
            "part_id": str(part.id), "vessel_id": str(data["vessel_a"]),
        }, headers=headers)

    r = await client.get("/api/v1/part-requests", headers=headers)
    assert r.json()["total"] == 2

    rid = r.json()["items"][0]["id"]
    await client.patch(f"/api/v1/part-requests/{rid}", json={"status": "in_review"},
                       headers=await auth_headers(client, "supply_a"))

    filtered = await client.get("/api/v1/part-requests?status=in_review", headers=headers)
    assert filtered.json()["total"] == 1


async def test_registry_scoped_to_organization(client, data):
    bosch, _ = await _catalog_with_offers()
    await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
    }, headers=await auth_headers(client, "mech_a"))

    r = await client.get("/api/v1/part-requests", headers=await auth_headers(client, "admin_b"))
    assert r.json()["total"] == 0        # чужая организация ничего не видит


async def test_supply_manager_sees_all_org_requests(client, data):
    """Механик видит только свои заявки, снабженец — все по организации."""
    bosch, _ = await _catalog_with_offers()
    await client.post("/api/v1/part-requests", json={
        "part_id": str(bosch.id), "vessel_id": str(data["vessel_a"]),
    }, headers=await auth_headers(client, "mech_a"))

    supply = await client.get("/api/v1/part-requests", headers=await auth_headers(client, "supply_a"))
    assert supply.json()["total"] == 1
