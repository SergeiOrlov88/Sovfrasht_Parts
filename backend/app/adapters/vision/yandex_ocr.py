# -*- coding: utf-8 -*-
"""Основной провайдер: Yandex Vision OCR — чтение шильдика (docs/06)."""
from __future__ import annotations

import base64
import re

from app.adapters.vision.base import OcrProvider, OcrResult, PhotoInput
from app.adapters.vision.http import post_json
from app.core.config import settings

# Маркировка на шильдиках: обычно 6+ символов из букв/цифр с дефисами и точками,
# и хотя бы одна цифра. Отсекаем словарные слова вроде "PUMP" или "MADE IN".
_PART_NUMBER = re.compile(r"\b(?=[A-Z0-9./-]{6,32}\b)(?=[^\s]*\d)[A-Z0-9][A-Z0-9./-]{4,31}\b")

# Метки, после которых на шильдике идёт нужное значение
_LABELS = {
    "oem_number": ("PART NO", "PART NUMBER", "P/N", "PN", "ART", "ARTICLE",
                   "КАТ. №", "АРТИКУЛ", "НОМЕР ДЕТАЛИ"),
    "serial_number": ("SERIAL", "SER NO", "S/N", "SN", "ЗАВ. №", "СЕРИЙНЫЙ"),
    "maker": ("MAKER", "MANUFACTURER", "MFG", "ПРОИЗВОДИТЕЛЬ", "ИЗГОТОВИТЕЛЬ"),
}


def _after_label(text_upper: str, labels: tuple[str, ...]) -> str | None:
    """Достаёт значение, идущее сразу за меткой."""
    for label in labels:
        idx = text_upper.find(label)
        if idx == -1:
            continue
        tail = text_upper[idx + len(label):].lstrip(" :.\t")
        value = tail.split("\n", 1)[0].strip()
        if value:
            return value[:128]
    return None


def parse_nameplate(text: str) -> dict:
    """Разбор текста шильдика. Вынесен отдельно — покрыт тестами без сети."""
    upper = text.upper()
    oem = _after_label(upper, _LABELS["oem_number"])
    if not oem:
        # метки нет — берём самый длинный «номероподобный» токен
        candidates = _PART_NUMBER.findall(upper)
        oem = max(candidates, key=len) if candidates else None
    return {
        "oem_number": oem,
        "serial_number": _after_label(upper, _LABELS["serial_number"]),
        "maker": _after_label(upper, _LABELS["maker"]),
    }


class YandexOcrProvider(OcrProvider):
    """Yandex Vision OCR. Ключ и folder_id — из окружения (NFR-SEC-05)."""

    name = "yandex_ocr"

    async def recognize_text(self, photo: PhotoInput) -> OcrResult:
        payload = {
            "mimeType": photo.mime_type,
            "languageCodes": ["ru", "en"],
            "model": "page",
            "content": base64.b64encode(photo.content).decode("ascii"),
        }
        headers = {
            "Authorization": f"Api-Key {settings.yandex_api_key}",
            "x-folder-id": settings.yandex_folder_id,
            "x-data-logging-enabled": "false",   # не отдаём изображения на обучение провайдеру
        }
        data = await post_json(settings.yandex_ocr_url, json=payload,
                               headers=headers, provider=self.name)

        block = (data.get("result") or {}).get("textAnnotation") or {}
        text = (block.get("fullText") or "").strip()
        parsed = parse_nameplate(text)

        return OcrResult(
            text=text,
            maker=parsed["maker"],
            oem_number=parsed["oem_number"],
            serial_number=parsed["serial_number"],
            model_version=f"{self.name}:page",
            # длинный связный текст = уверенное чтение; короткий обрывок — нет
            text_confidence=min(100, len(text)) if text else 0,
            raw={"fullText": text},
        )
