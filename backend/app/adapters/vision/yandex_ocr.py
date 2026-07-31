# -*- coding: utf-8 -*-
"""Основной провайдер: Yandex Vision OCR — чтение шильдика (docs/06)."""
from __future__ import annotations

import base64

from app.adapters.vision.base import OcrProvider, OcrResult, PhotoInput
from app.adapters.vision.nameplate import parse_nameplate
from app.adapters.vision.http import post_json
from app.core.config import settings

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
            maker=parsed.maker,
            oem_number=parsed.oem_number,
            serial_number=parsed.serial_number,
            model_version=f"{self.name}:page",
            # длинный связный текст = уверенное чтение; короткий обрывок — нет
            text_confidence=min(100, len(text)) if text else 0,
            raw={"fullText": text, "tokens": parsed.tokens},
        )
