# -*- coding: utf-8 -*-
"""Ремонт или замена (D1, FR-REPAIR-01/02)."""
import uuid

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.catalog import Part, RepairInfo
from app.services import catalog_import, offers_import, repair_service
from app.services.repair_service import RepairRule
from tests.conftest import auth_headers

RULES = {
    "cr_injector": RepairRule("cr_injector", "fuel_equipment", "replace",
                              "Ремонт CR-инжектора требует стенда и оригинальных распылителей.",
                              "50–60%", "5–8 дн"),
    "impeller": RepairRule("impeller", "pump", "repair",
                           "Крыльчатка обычно восстанавливается проточкой и балансировкой.",
                           "30–50%", "1–3 дн"),
    "screw_pump": RepairRule("screw_pump", "pump", "repair",
                             "Винтовой насос ремонтопригоден в условиях судоремонта.",
                             "30–50%", "2–5 дн"),
    "mech_seal": RepairRule("mech_seal", "pump", "replace",
                            "Торцевое уплотнение — расходник, ремонт нецелесообразен.",
                            None, None),
}


async def _catalog():
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка Common Rail Bosch", category="fuel_equipment", maker="Bosch",
                 oem_number="0445120100", equipment="Дизель CR",
                 specs='{"subtype":"cr_injector","num_status":"verified"}'),
            dict(name="Импеллер насоса забортной воды", category="pump", maker="Johnson",
                 oem_number="09-1027B", equipment="Насос забортной воды",
                 specs='{"subtype":"impeller"}'),
            dict(name="Насос винтовой", category="pump", maker="IMO AB",
                 oem_number="ACE032N3", equipment="Топливоперекачивающая система",
                 specs='{"subtype":"screw_pump"}'),
            dict(name="Деталь неизвестного типа", category="pump", maker="X",
                 oem_number="ZZ0001", specs='{"subtype":"exotic_thing"}'),
        ])
    async with SessionLocal() as db:
        await offers_import.import_offers(db, [
            dict(part_oem="0445120100", supplier_name="ShipServ", supplier_type="площадка",
                 price="$1 190", lead_time="7–10 дн", stock_status="in"),
            dict(part_oem="0445120100", supplier_name="ReMarine", supplier_type="восстановление",
                 price="$690", lead_time="5–8 дн", stock_status="low"),
            dict(part_oem="09-1027B", supplier_name="Marine Direct", supplier_type="дистрибьютор",
                 price="$210", lead_time="3–5 дн", stock_status="in"),
        ])
    async with SessionLocal() as db:
        await repair_service.apply_rules(db, RULES)


async def _part(oem):
    async with SessionLocal() as db:
        from app.adapters.vision.nameplate import normalize_code
        return await db.scalar(select(Part).where(Part.oem_number_norm == normalize_code(oem)))


# ── Разбор правил ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("50–60%", (50, 60)), ("30-50%", (30, 50)), ("40%", (40, 40)),
    ("—", None), ("", None), (None, None),
])
def test_parse_share(raw, expected):
    assert repair_service.parse_share(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("$1 190", 1190.0), ("€820", 820.0), ("1190", 1190.0), ("—", None), (None, None),
])
def test_parse_price(raw, expected):
    assert repair_service.parse_price(raw) == expected


def test_estimate_repair_cost_range():
    """Ремонт = доля от цены замены, валюта сохраняется."""
    assert repair_service.estimate_repair_cost("$1 190", "50–60%") == "$595–$714"


def test_estimate_repair_cost_single_value():
    assert repair_service.estimate_repair_cost("$200", "40%") == "$80"


def test_estimate_without_share_is_none():
    assert repair_service.estimate_repair_cost("$1 190", None) is None


def test_estimate_without_price_is_none():
    assert repair_service.estimate_repair_cost(None, "50–60%") is None


# ── Применение правил ────────────────────────────────────────────────────────

async def test_rules_applied_by_subtype(client, data):
    await _catalog()
    async with SessionLocal() as db:
        infos = {
            (await db.scalar(select(Part).where(Part.id == i.part_id))).name: i
            for i in (await db.scalars(select(RepairInfo))).all()
        }
    assert infos["Форсунка Common Rail Bosch"].verdict == "replace"
    assert infos["Импеллер насоса забортной воды"].verdict == "repair"
    assert infos["Импеллер насоса забортной воды"].repair_share == "30–50%"
    assert infos["Импеллер насоса забортной воды"].rule_subtype == "impeller"


async def test_unknown_subtype_gets_unknown_verdict(client, data):
    """Правила нет — честный unknown, а не догадка."""
    await _catalog()
    part = await _part("ZZ0001")
    async with SessionLocal() as db:
        info = await db.scalar(select(RepairInfo).where(RepairInfo.part_id == part.id))
    assert info.verdict == "unknown"
    assert "правила пока нет" in info.rationale


async def test_apply_rules_is_idempotent(client, data):
    await _catalog()
    async with SessionLocal() as db:
        report = await repair_service.apply_rules(db, RULES)
    assert report.created == 0 and report.updated == 4


async def test_rule_without_share_keeps_none(client, data):
    """«—» в файле — это «неприменимо», а не значение."""
    rules = {"mech_seal": RULES["mech_seal"]}
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Торцевое уплотнение", category="pump", maker="AL",
                 oem_number="TS4530", specs='{"subtype":"mech_seal"}')])
    async with SessionLocal() as db:
        await repair_service.apply_rules(db, rules)
    part = await _part("TS4530")
    async with SessionLocal() as db:
        info = await db.scalar(select(RepairInfo).where(RepairInfo.part_id == part.id))
    assert info.verdict == "replace"
    assert info.repair_share is None and info.repair_time is None


def test_load_rules_treats_dash_as_empty(tmp_path):
    path = tmp_path / "rules.csv"
    path.write_text(
        "subtype,category,default_verdict,rationale,typical_repair_share,typical_repair_time\n"
        "nozzle,fuel_equipment,replace,Расходник,—,—\n", encoding="utf-8")
    rules = repair_service.load_rules(path)
    assert rules["nozzle"].typical_repair_share is None
    assert rules["nozzle"].default_verdict == "replace"


# ── Эндпоинт ─────────────────────────────────────────────────────────────────

async def test_repair_advice_replace_with_reman(client, data):
    """Форсунка Bosch: вердикт replace, восстановление показано отдельно."""
    await _catalog()
    part = await _part("0445120100")
    r = await client.get(f"/api/v1/parts/{part.id}/repair",
                         headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "replace"
    assert body["rule_subtype"] == "cr_injector"
    assert "стенда" in body["rationale"]
    # Замена — из лучшего НОВОГО предложения, а не из восстановленного
    assert body["estimate"]["replace_price"] == "$1 190"
    assert body["estimate"]["replace_supplier"] == "ShipServ"
    assert body["estimate"]["repair_cost_estimate"] == "$595–$714"
    assert body["estimate"]["repair_share"] == "50–60%"
    # Восстановленная деталь — отдельный путь
    assert len(body["reman_offers"]) == 1
    assert body["reman_offers"][0]["price"] == "$690"


async def test_repair_advice_repair_verdict(client, data):
    """Импеллер: вердикт repair, оценка стоимости от цены замены."""
    await _catalog()
    part = await _part("09-1027B")
    body = (await client.get(f"/api/v1/parts/{part.id}/repair",
                             headers=await auth_headers(client, "mech_a"))).json()
    assert body["verdict"] == "repair"
    assert body["estimate"]["replace_price"] == "$210"
    assert body["estimate"]["repair_cost_estimate"] == "$63–$105"
    assert body["estimate"]["repair_time"] == "1–3 дн"
    assert body["reman_offers"] == []


async def test_repair_advice_without_offers(client, data):
    """Цен нет — вердикт и обоснование всё равно выдаются."""
    await _catalog()
    part = await _part("ACE032N3")
    body = (await client.get(f"/api/v1/parts/{part.id}/repair",
                             headers=await auth_headers(client, "mech_a"))).json()
    assert body["verdict"] == "repair"
    assert body["estimate"]["replace_price"] is None
    assert body["estimate"]["repair_cost_estimate"] is None
    assert body["estimate"]["repair_share"] == "30–50%"


@pytest.mark.parametrize("oem", ["0445120100", "09-1027B", "ACE032N3", "ZZ0001"])
async def test_disclaimer_always_present(client, data, oem):
    """FR-REPAIR-02: дисклеймер обязателен при любом вердикте."""
    await _catalog()
    part = await _part(oem)
    body = (await client.get(f"/api/v1/parts/{part.id}/repair",
                             headers=await auth_headers(client, "mech_a"))).json()
    assert body["disclaimer"]
    assert "механик" in body["disclaimer"]
    assert "простоя" in body["disclaimer"]


async def test_repair_advice_unknown_verdict(client, data):
    await _catalog()
    part = await _part("ZZ0001")
    body = (await client.get(f"/api/v1/parts/{part.id}/repair",
                             headers=await auth_headers(client, "mech_a"))).json()
    assert body["verdict"] == "unknown"
    assert body["disclaimer"]


async def test_repair_advice_unknown_part(client, data):
    r = await client.get(f"/api/v1/parts/{uuid.uuid4()}/repair",
                         headers=await auth_headers(client, "mech_a"))
    assert r.status_code == 404


async def test_repair_advice_requires_auth(client, data):
    await _catalog()
    part = await _part("0445120100")
    r = await client.get(f"/api/v1/parts/{part.id}/repair")
    assert r.status_code == 401
