# -*- coding: utf-8 -*-
"""Сопоставление с каталогом (A3) и загрузчик справочника."""
import pytest

from app.core.database import SessionLocal
from app.models.catalog import Part, PartAlias, PartAlternative
from app.services import catalog_import, catalog_service
from app.services.catalog_service import CatalogStatus, MatchMethod


async def _seed_catalog():
    """Небольшой каталог: две форсунки разных производителей и насос."""
    async with SessionLocal() as db:
        rows = [
            dict(name="Форсунка Common Rail", category="fuel_equipment", maker="BOSCH",
                 impa_code="350101", oem_number="0445120123",
                 aliases="0 445 120 123", specs='{"давление_бар":1800}'),
            dict(name="Форсунка Common Rail", category="fuel_equipment", maker="DENSO",
                 oem_number="095000-6353", aliases="095000 6353"),
            dict(name="Насос центробежный судовой", category="pumps", maker="GRUNDFOS",
                 impa_code="352410", oem_number="NK50-200"),
        ]
        await catalog_import.import_rows(db, rows)


# ── Загрузчик ────────────────────────────────────────────────────────────────

async def test_import_creates_parts_and_normalizes(client, data):
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [
            dict(name="Форсунка", category="fuel_equipment", maker="BOSCH",
                 oem_number="0 445 120 123", aliases="0445-120-123;BOSCH0445120123"),
        ])
    assert report.created == 1 and report.aliases == 2
    async with SessionLocal() as db:
        part = await db.scalar(catalog_service.select(Part))
        assert part.oem_number_norm == "0445120123"     # нормализовано
        assert part.maker_norm == "BOSCH"


async def test_import_is_idempotent(client, data):
    row = dict(name="Форсунка", maker="BOSCH", oem_number="0445120123")
    async with SessionLocal() as db:
        first = await catalog_import.import_rows(db, [row])
    async with SessionLocal() as db:
        second = await catalog_import.import_rows(db, [row])
    assert first.created == 1 and second.created == 0 and second.updated == 1


async def test_import_accepts_part_without_codes(client, data):
    """У части судовых дизелей номера непубличны — такие позиции грузим,
    опознание пойдёт по name/maker/equipment (решение заказчика)."""
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [
            dict(name="Форсунка Wärtsilä 46", category="fuel_equipment",
                 maker="Wärtsilä", equipment="Wärtsilä 46")])
    assert report.created == 1 and report.skipped == 0


async def test_import_rejects_unidentifiable_row(client, data):
    """Мягкий инвариант (docs/07 §3): без производителя И без оборудования
    позицию нечем опознать — такую строку не принимаем."""
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [dict(name="Деталь ниоткуда")])
    assert report.skipped == 1
    assert "нечем опознать" in report.errors[0]


async def test_import_accepts_row_with_equipment_only(client, data):
    """Производителя нет, но есть оборудование — этого достаточно."""
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [
            dict(name="Плунжерная пара", equipment="Wärtsilä 6L32")])
    assert report.created == 1
    assert any("сопоставление пойдёт только по оборудованию" in w for w in report.warnings)


async def test_match_codeless_part_by_maker_and_equipment(client, data):
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка Wärtsilä 46", category="fuel_equipment",
                 maker="Wartsila", equipment="Wärtsilä 46")])
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, maker="Wartsila", equipment_hint="46")
    assert outcome.status is CatalogStatus.candidates
    assert outcome.candidates[0].part.name.startswith("Форсунка")


async def test_import_rejects_row_without_name(client, data):
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [dict(maker="BOSCH", oem_number="123456")])
    assert report.skipped == 1 and "name" in report.errors[0]


async def test_import_warns_on_unknown_category(client, data):
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [
            dict(name="Деталь", category="космос", maker="BOSCH", oem_number="123456")])
    assert any("незнакомая категория" in w for w in report.warnings)


async def test_import_dry_run_writes_nothing(client, data):
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(
            db, [dict(name="Форсунка", maker="BOSCH", oem_number="0445120123")], dry_run=True)
    assert report.created == 1
    async with SessionLocal() as db:
        assert await db.scalar(catalog_service.select(Part)) is None


async def test_import_links_alternatives_second_pass(client, data):
    """Аналог может встретиться в файле позже — связь ставится вторым проходом."""
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [
            dict(name="Форсунка BOSCH", maker="BOSCH", oem_number="0445120123",
                 alt_oem="095000-6353"),
            dict(name="Форсунка DENSO", maker="DENSO", oem_number="095000-6353"),
        ])
    assert report.alternatives == 1
    async with SessionLocal() as db:
        assert await db.scalar(catalog_service.select(PartAlternative)) is not None


async def test_import_warns_when_alternative_missing(client, data):
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [
            dict(name="Форсунка", maker="BOSCH", oem_number="0445120123", alt_oem="НЕТ-ТАКОГО"),
        ])
    assert any("не найден в каталоге" in w for w in report.warnings)


async def test_import_bad_specs_json_warns_but_loads(client, data):
    async with SessionLocal() as db:
        report = await catalog_import.import_rows(db, [
            dict(name="Форсунка", maker="BOSCH", oem_number="0445120123", specs="{это не json"),
        ])
    assert report.created == 1
    assert any("specs" in w for w in report.warnings)


def test_read_rows_detects_delimiter(tmp_path):
    """Аналитики выгружают и через ';', и через ','."""
    for delim in (";", ","):
        path = tmp_path / f"parts{delim.encode().hex()}.csv"
        path.write_text(f"name{delim}oem_number\nФорсунка{delim}0445120123\n", encoding="utf-8")
        rows = catalog_import.read_rows(path)
        assert rows[0]["oem_number"] == "0445120123"


# ── Матчинг ──────────────────────────────────────────────────────────────────

async def test_exact_match_by_oem(client, data):
    await _seed_catalog()
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="0445120123")
    assert outcome.status is CatalogStatus.matched
    assert outcome.method is MatchMethod.oem
    assert outcome.primary.maker == "BOSCH"


async def test_exact_match_ignores_spaces_and_dashes(client, data):
    """Номер с шильдика приезжает с пробелами — точное совпадение обязано сработать."""
    await _seed_catalog()
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="0 445-120 123")
    assert outcome.status is CatalogStatus.matched


async def test_match_by_impa_has_priority(client, data):
    await _seed_catalog()
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, impa_code="350101", oem_number="095000-6353")
    assert outcome.method is MatchMethod.impa
    assert outcome.primary.impa_code == "350101"


async def test_match_by_alias(client, data):
    await _seed_catalog()
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="095000 6353")
    assert outcome.status is CatalogStatus.matched
    assert outcome.primary.maker == "DENSO"


async def test_match_by_ocr_variant(client, data):
    """OCR прочитал O вместо 0 — вариант номера всё равно находит деталь."""
    await _seed_catalog()
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="O445I2O123")
    assert outcome.status is CatalogStatus.matched
    assert outcome.method is MatchMethod.ocr_variant
    assert outcome.primary.oem_number_norm == "0445120123"


async def test_maker_resolves_ambiguity(client, data):
    """Один номер у двух производителей — разрешаем по maker."""
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка A", maker="BOSCH", oem_number="SAME123"),
            dict(name="Форсунка B", maker="DENSO", oem_number="SAME123"),
        ])
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="SAME123", maker="DENSO")
    assert outcome.primary.maker == "DENSO"
    assert len(outcome.candidates) == 2


async def test_prefix_match_gives_candidates(client, data):
    """OCR потерял хвост номера — получаем кандидатов, а не точное совпадение."""
    await _seed_catalog()
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="04451201")
    assert outcome.status is CatalogStatus.candidates
    assert outcome.primary is None
    assert outcome.candidates[0].part.oem_number_norm == "0445120123"


async def test_not_found_is_honest(client, data):
    """Ключевое требование заказчика: нет в каталоге — так и говорим,
    похожее силой не подбираем."""
    await _seed_catalog()
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="ZZZ999888777")
    assert outcome.status is CatalogStatus.not_found
    assert outcome.primary is None
    assert outcome.candidates == []


async def test_empty_catalog_returns_not_found(client, data):
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="0445120123")
    assert outcome.status is CatalogStatus.not_found


async def test_alternatives_exclude_primary(client, data):
    """NFR-ACC-02: альтернативы — это кандидаты без основной позиции."""
    async with SessionLocal() as db:
        await catalog_import.import_rows(db, [
            dict(name="Форсунка A", maker="BOSCH", oem_number="SAME123"),
            dict(name="Форсунка B", maker="DENSO", oem_number="SAME123"),
        ])
    async with SessionLocal() as db:
        outcome = await catalog_service.match(db, oem_number="SAME123", maker="BOSCH")
    assert len(outcome.alternatives) == 1
    assert outcome.alternatives[0].part.maker == "DENSO"


# ── Влияние матчинга на confidence ───────────────────────────────────────────

@pytest.mark.parametrize("method,floor", [
    (MatchMethod.impa, 85), (MatchMethod.issa, 85),
    (MatchMethod.oem, 80), (MatchMethod.alias, 78), (MatchMethod.ocr_variant, 72),
])
def test_exact_match_raises_confidence(method, floor):
    outcome = catalog_service.MatchOutcome(status=CatalogStatus.matched, method=method)
    assert catalog_service.adjust_confidence(30, outcome) == floor


def test_exact_match_does_not_lower_high_confidence():
    outcome = catalog_service.MatchOutcome(status=CatalogStatus.matched, method=MatchMethod.oem)
    assert catalog_service.adjust_confidence(95, outcome) == 95


def test_not_found_lowers_confidence():
    outcome = catalog_service.MatchOutcome(status=CatalogStatus.not_found)
    assert catalog_service.adjust_confidence(80, outcome) == 40


def test_candidates_scale_with_similarity():
    class _P:
        id = "x"
    low = catalog_service.MatchOutcome(
        status=CatalogStatus.candidates,
        candidates=[catalog_service.Candidate(_P(), 0.4, MatchMethod.trigram)])
    high = catalog_service.MatchOutcome(
        status=CatalogStatus.candidates,
        candidates=[catalog_service.Candidate(_P(), 0.9, MatchMethod.trigram)])
    assert catalog_service.adjust_confidence(80, low) < catalog_service.adjust_confidence(80, high)
