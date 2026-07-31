# -*- coding: utf-8 -*-
"""Разбор шильдика: вендоры, паттерны, отсев мусора, варианты OCR-неоднозначностей."""
import pytest

from app.adapters.vision.nameplate import (
    code_variants,
    detect_vendor,
    is_noise,
    normalize_code,
    parse_nameplate,
)


# ── Нормализация ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("0445120123", "0445120123"),
    ("0 445 120 123", "0445120123"),
    ("0445-120-123", "0445120123"),
    ("  0445.120.123  ", "0445120123"),
    ("wk94046", "WK94046"),
    (None, ""),
])
def test_normalize_code(raw, expected):
    assert normalize_code(raw) == expected


def test_normalize_converts_cyrillic_lookalikes():
    """OCR подставляет русские буквы вместо латинских — приводим к одному виду."""
    assert normalize_code("ВОSСН") == normalize_code("BOSCH")


# ── Производители ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,vendor", [
    ("ROBERT BOSCH GMBH\nMADE IN GERMANY", "BOSCH"),
    ("NIPPONDENSO CO LTD", "DENSO"),
    ("WÄRTSILÄ FINLAND", "WARTSILA"),
    ("ALFA LAVAL TUMBA AB", "ALFA LAVAL"),
    ("НЕИЗВЕСТНЫЙ ЗАВОД", None),
])
def test_detect_vendor(text, vendor):
    assert detect_vendor(text.upper()) == vendor


# ── Отсев не-номеров ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("token", ["2019", "24V", "50HZ", "M12X1.5", "ISO9001",
                                   "DIN", "MADE", "GERMANY", "IP54", "1800BAR"])
def test_is_noise(token):
    assert is_noise(token) is True


@pytest.mark.parametrize("token", ["0445120123", "095000-6353", "119773-42100", "WK94046"])
def test_real_numbers_are_not_noise(token):
    assert is_noise(token) is False


# ── Приоритет извлечения ─────────────────────────────────────────────────────

def test_label_has_priority():
    parsed = parse_nameplate("BOSCH\nPART NO: 0445120123\nSERIAL: 998877")
    assert parsed.oem_number == "0445120123"
    assert parsed.serial_number == "998877"
    assert parsed.maker == "BOSCH"


def test_vendor_pattern_when_no_label():
    """Метки нет, но вендор опознан — берём номер по его формату."""
    parsed = parse_nameplate("ROBERT BOSCH GMBH\n0 445 120 123\nMADE IN GERMANY 2019")
    assert normalize_code(parsed.oem_number) == "0445120123"
    assert parsed.maker == "BOSCH"


def test_denso_pattern():
    parsed = parse_nameplate("DENSO CORPORATION\n095000-6353\n24V")
    assert parsed.oem_number == "095000-6353"


def test_yanmar_pattern():
    parsed = parse_nameplate("YANMAR CO LTD\n119773-42100")
    assert parsed.oem_number == "119773-42100"


def test_falls_back_to_longest_token():
    """Ни метки, ни известного вендора — берём самый длинный номероподобный токен."""
    parsed = parse_nameplate("UNKNOWN PLANT\nXY12345678\n2019\n24V")
    assert parsed.oem_number == "XY12345678"


def test_noise_does_not_win_over_number():
    """Год и напряжение не должны побеждать настоящий номер."""
    parsed = parse_nameplate("SOME MAKER\n2019\n24V\nM12X1.5\nAB123456789")
    assert parsed.oem_number == "AB123456789"


def test_serial_not_mistaken_for_part_number():
    parsed = parse_nameplate("UNKNOWN\nS/N: SER9988776655\nPRT4455667788")
    assert normalize_code(parsed.oem_number) != normalize_code(parsed.serial_number)


def test_tokens_are_collected_for_calibration():
    """Все токены сохраняются — на них потом калибруем эвристику по фото."""
    parsed = parse_nameplate("BOSCH\nPART NO 0445120123\nDRAWING 7788990011\n2019")
    tokens = {t["normalized"] for t in parsed.tokens}
    assert "0445120123" in tokens
    assert "7788990011" in tokens          # второй номер тоже сохранён
    assert "2019" not in tokens            # мусор отсеян
    chosen = [t for t in parsed.tokens if t.get("chosen")]
    assert len(chosen) == 1 and chosen[0]["source"] == "label"


def test_empty_text():
    parsed = parse_nameplate("")
    assert parsed.oem_number is None and parsed.tokens == []


# ── Варианты OCR-неоднозначностей ────────────────────────────────────────────

def test_code_variants_includes_original_first():
    variants = code_variants("0445120123")
    assert variants[0] == "0445120123"


def test_code_variants_swaps_ambiguous_chars():
    """O/0 путаются постоянно — вариант с исправлением должен быть в списке."""
    variants = code_variants("O445120123")
    assert "0445120123" in variants


def test_code_variants_bounded():
    """Комбинаторного взрыва быть не должно."""
    variants = code_variants("OOOOIIIISSSS8888")
    assert len(variants) <= 16


def test_code_variants_empty():
    assert code_variants("") == []
