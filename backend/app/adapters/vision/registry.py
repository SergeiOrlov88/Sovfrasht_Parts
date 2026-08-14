# -*- coding: utf-8 -*-
"""Выбор провайдеров по конфигурации. Смена провайдера — правка .env, не кода."""
from __future__ import annotations

import logging

from app.adapters.vision.base import (
    OcrProvider,
    OcrResult,
    PhotoInput,
    VisionProvider,
    VisionResult,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class StubOcrProvider(OcrProvider):
    """Заглушка: провайдер не настроен. Возвращает пустой результат, а не падает —
    конвейер должен деградировать мягко (NFR-REL-03)."""

    name = "stub_ocr"

    async def recognize_text(self, photo: PhotoInput) -> OcrResult:
        return OcrResult(model_version=f"{self.name}:none")


class StubVisionProvider(VisionProvider):
    name = "stub_vision"

    async def describe(self, photos: list[PhotoInput]) -> VisionResult:
        return VisionResult(model_version=f"{self.name}:none")


def get_ocr_provider() -> OcrProvider:
    if settings.ocr_provider == "yandex":
        if not (settings.yandex_api_key and settings.yandex_folder_id):
            # Ключа нет — не пытаемся ходить в сеть и не роняем скан
            logger.warning("OCR_PROVIDER=yandex, но YANDEX_API_KEY/FOLDER_ID пусты — заглушка")
            return StubOcrProvider()
        from app.adapters.vision.yandex_ocr import YandexOcrProvider
        return YandexOcrProvider()
    return StubOcrProvider()


def get_vision_provider() -> VisionProvider:
    if settings.vision_provider == "openrouter":
        if not settings.openrouter_api_key:
            # Ключа нет — не ходим в сеть и не роняем скан (NFR-REL-03)
            logger.warning("VISION_PROVIDER=openrouter, но OPENROUTER_API_KEY пуст — заглушка")
            return StubVisionProvider()
        from app.adapters.vision.openrouter_vision import OpenRouterVisionProvider
        return OpenRouterVisionProvider()
    if settings.vision_provider == "llm":
        if not (settings.vision_llm_url and settings.vision_llm_api_key):
            logger.warning("VISION_PROVIDER=llm, но URL/ключ не заданы — заглушка")
            return StubVisionProvider()
        from app.adapters.vision.vision_llm import VisionLlmProvider
        return VisionLlmProvider()
    return StubVisionProvider()
