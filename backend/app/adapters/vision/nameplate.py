# -*- coding: utf-8 -*-
"""Разбор текста шильдика: производитель, номер детали, серийный номер.

Приоритет извлечения номера: явная метка → вендорный паттерн → самый длинный
номероподобный токен. Вендорный слой важен потому, что метки (`PART NO`) на
реальных шильдиках есть далеко не всегда, а название производителя — почти всегда.

Пороги и паттерны рассчитаны на калибровку по реальным фото: до их появления
все распознанные токены сохраняются в Recognition.detected_tokens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Нормализация ─────────────────────────────────────────────────────────────
# Кириллические буквы, визуально совпадающие с латинскими: OCR их регулярно
# подменяет, и номер «0445120123» приезжает с русской «О» внутри.
_CYR_TO_LAT = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
    "О": "O", "Р": "P", "Т": "T", "У": "Y", "Х": "X",
})


def normalize_code(value: str | None) -> str:
    """Каноническая форма кода: верхний регистр, только A-Z0-9.

    Одинаково применяется к каталогу и к строке из OCR — иначе «точное
    совпадение» промахивается на пробелах и дефисах.
    """
    if not value:
        return ""
    upper = value.upper().translate(_CYR_TO_LAT)
    return re.sub(r"[^A-Z0-9]", "", upper)


# ── Производители ────────────────────────────────────────────────────────────
# Ключ — каноническое имя, значения — как оно встречается на шильдиках.
VENDORS: dict[str, tuple[str, ...]] = {
    "BOSCH": ("BOSCH", "ROBERT BOSCH"),
    "DENSO": ("DENSO", "NIPPONDENSO", "NIPPON DENSO"),
    "DELPHI": ("DELPHI",),
    "YANMAR": ("YANMAR",),
    "MAN": ("MAN B&W", "MAN DIESEL", "MAN ENERGY", "MAN "),
    "WARTSILA": ("WARTSILA", "WÄRTSILÄ", "WARTSILÄ"),
    "CATERPILLAR": ("CATERPILLAR", "CAT ", "PERKINS"),
    "VOLVO PENTA": ("VOLVO PENTA", "VOLVO"),
    "CUMMINS": ("CUMMINS",),
    "MITSUBISHI": ("MITSUBISHI",),
    "DAIHATSU": ("DAIHATSU",),
    "ALFA LAVAL": ("ALFA LAVAL", "ALFALAVAL"),
    "GRUNDFOS": ("GRUNDFOS",),
    "IMO AB": ("IMO AB", "IMO PUMP"),
    "DESMI": ("DESMI",),
    "ALLWEILER": ("ALLWEILER",),
    "KRACHT": ("KRACHT",),
    "ZEXEL": ("ZEXEL",),
    "STANADYNE": ("STANADYNE",),
}

# Формат номера у конкретных производителей: если вендор опознан, такой паттерн
# надёжнее, чем «самый длинный токен».
VENDOR_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    "BOSCH": (re.compile(r"\b0\s?\d{3}\s?\d{3}\s?\d{3}\b"),      # 0 445 120 123
              re.compile(r"\bF\s?00[A-Z0-9]\s?[A-Z0-9]{5,7}\b")),
    "DENSO": (re.compile(r"\b\d{6}-\d{4}\b"),                     # 095000-6353
              re.compile(r"\bDCRP\d{6,8}\b")),
    "YANMAR": (re.compile(r"\b\d{6}-\d{5,6}\b"),),                # 119773-42100
    "CATERPILLAR": (re.compile(r"\b\d{3}-\d{4}\b"),),             # 320-0680
    "CUMMINS": (re.compile(r"\b\d{7}\b"),),
    "DELPHI": (re.compile(r"\b[A-Z]{3}\d{6}\b"),),                # EJB R0 …
    "ZEXEL": (re.compile(r"\b\d{9}\b"),),
}

# ── Метки перед значением ────────────────────────────────────────────────────
LABELS: dict[str, tuple[str, ...]] = {
    "oem_number": ("PART NO", "PART NUMBER", "PART-NO", "P/N", "PN NO", "PN",
                   "ARTICLE NO", "ARTICLE", "ART NO", "ART.",
                   "КАТ. №", "КАТ.№", "КАТАЛОЖНЫЙ", "АРТИКУЛ", "НОМЕР ДЕТАЛИ", "ДЕТАЛЬ №"),
    "serial_number": ("SERIAL NO", "SERIAL", "SER NO", "S/N", "SN NO", "SN",
                      "ЗАВ. №", "ЗАВ.№", "СЕРИЙНЫЙ", "СЕР. №"),
    "maker": ("MAKER", "MANUFACTURER", "MFG BY", "MFG", "MADE BY",
              "ПРОИЗВОДИТЕЛЬ", "ИЗГОТОВИТЕЛЬ"),
}

# ── Отсев того, что похоже на номер, но им не является ───────────────────────
_NOISE_PATTERNS = (
    re.compile(r"^(19|20)\d{2}$"),                       # год: 2019
    re.compile(r"^\d{1,4}(V|VDC|VAC|HZ|KW|KG|MM|BAR|PSI|RPM|A)$"),   # 24V, 50HZ, 1800BAR
    re.compile(r"^M\d{1,2}([X×]\d+([.,]\d+)?)?$"),       # резьба M12x1.5
    re.compile(r"^(ISO|DIN|EN|GOST|ГОСТ|ANSI|JIS|IP)\d*$"),
    re.compile(r"^(IP|NEMA)\d{2}$"),
)
_NOISE_WORDS = {
    "MADE", "IN", "GERMANY", "JAPAN", "CHINA", "KOREA", "ITALY", "FRANCE", "USA",
    "TYPE", "MODEL", "SIZE", "CLASS", "MAX", "MIN", "NO", "NR", "REV",
    "СДЕЛАНО", "РОССИЯ", "ТИП", "МОДЕЛЬ", "МАРКА",
}

# Номероподобный токен: 5+ символов из [A-Z0-9./-], минимум одна цифра
_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9./-]{4,31}")

# Символы, которые OCR путает между собой. Ключ -> чем ещё это может быть.
AMBIGUOUS = {"O": "0", "0": "O", "I": "1", "1": "I", "L": "1",
             "S": "5", "5": "S", "B": "8", "8": "B", "Z": "2", "2": "Z"}
_MAX_VARIANTS = 16          # комбинаторный взрыв не нужен: берём разумный потолок


@dataclass(slots=True)
class NameplateParse:
    maker: str | None = None
    oem_number: str | None = None
    serial_number: str | None = None
    # Все номероподобные токены с указанием, откуда взяты — сырьё для калибровки
    # эвристики, когда появятся реальные фото шильдиков.
    tokens: list[dict] = field(default_factory=list)


def is_noise(token: str) -> bool:
    """Похоже на номер, но им не является: год, напряжение, резьба, стандарт."""
    if token in _NOISE_WORDS:
        return True
    if not any(ch.isdigit() for ch in token):
        return True                                   # без цифр это не номер
    compact = token.replace(" ", "")
    return any(p.match(compact) for p in _NOISE_PATTERNS)


def detect_vendor(text_upper: str) -> str | None:
    """Ищем производителя по словарю — надёжнее метки MAKER, её часто нет."""
    for canonical, spellings in VENDORS.items():
        for spelling in spellings:
            if spelling in text_upper:
                return canonical
    return None


def _value_after_label(text_upper: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        idx = text_upper.find(label)
        if idx == -1:
            continue
        tail = text_upper[idx + len(label):].lstrip(" :.\t-")
        value = tail.split("\n", 1)[0].strip()
        if value:
            return value[:128]
    return None


def _by_vendor_pattern(text_upper: str, vendor: str | None) -> str | None:
    if not vendor:
        return None
    for pattern in VENDOR_PATTERNS.get(vendor, ()):  # noqa: B007
        match = pattern.search(text_upper)
        if match:
            return match.group(0).strip()
    return None


# Буква -> цифра: в номерах деталей цифр подавляющее большинство, поэтому
# «прочитал букву вместо цифры» — самая частая ошибка OCR.
_TO_DIGIT = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"}
_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z"}


def code_variants(code: str, limit: int = _MAX_VARIANTS) -> list[str]:
    """Варианты номера с учётом путаницы O/0, I/1, S/5, B/8, Z/2.

    Порядок важен: сначала «все буквы -> цифры» разом (типичный случай, когда OCR
    прочитал 0445120123 как O445I2O123), потом обратный вариант, и только затем
    одиночные замены. Иначе лимит выбирается на несущественных заменах, а нужная
    комбинация из нескольких подстановок так и не получается.
    """
    base = normalize_code(code)
    if not base:
        return []

    variants = [base]

    def _add(value: str) -> bool:
        if value not in variants:
            variants.append(value)
        return len(variants) >= limit

    # Массовые замены целиком по строке
    if _add("".join(_TO_DIGIT.get(ch, ch) for ch in base)):
        return variants
    if _add("".join(_TO_LETTER.get(ch, ch) for ch in base)):
        return variants

    # Одиночные замены — на случай, когда ошибся ровно один символ
    for i, ch in enumerate(base):
        alt = AMBIGUOUS.get(ch)
        if alt and _add(base[:i] + alt + base[i + 1:]):
            return variants
    return variants


def parse_nameplate(text: str) -> NameplateParse:
    """Полный разбор шильдика. Чистая функция — тестируется без сети."""
    if not text:
        return NameplateParse()

    upper = text.upper().translate(_CYR_TO_LAT)
    vendor = detect_vendor(upper)

    # Все номероподобные токены — и как сырьё для калибровки, и как запасной путь
    tokens: list[dict] = []
    for raw in _TOKEN.findall(upper):
        token = raw.strip("./-")
        if len(token) < 5 or is_noise(token):
            continue
        if not any(t["token"] == token for t in tokens):
            tokens.append({"token": token, "normalized": normalize_code(token)})

    serial = _value_after_label(upper, LABELS["serial_number"])

    # Приоритет 1: явная метка
    oem = _value_after_label(upper, LABELS["oem_number"])
    source = "label"
    # Приоритет 2: вендорный паттерн
    if not oem:
        oem = _by_vendor_pattern(upper, vendor)
        source = "vendor_pattern"
    # Приоритет 3: самый длинный токен, не совпадающий с серийным номером
    if not oem:
        serial_norm = normalize_code(serial)
        usable = [t for t in tokens if t["normalized"] != serial_norm]
        oem = max(usable, key=lambda t: len(t["normalized"]))["token"] if usable else None
        source = "longest_token"

    if oem:
        oem = oem.strip(" :.-")
        for token in tokens:
            if token["normalized"] == normalize_code(oem):
                token["chosen"] = True
                token["source"] = source

    maker = vendor or _value_after_label(upper, LABELS["maker"])

    return NameplateParse(
        maker=maker,
        oem_number=oem or None,
        serial_number=serial,
        tokens=tokens,
    )
