# -*- coding: utf-8 -*-
"""Единый интерфейс провайдеров распознавания (docs/06: «Адаптеры для vision/OCR»).

Ядро не знает, кто именно распознаёт: провайдер меняется в .env без правок
конвейера. Это же позволяет позже подключить собственную модель.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass(slots=True)
class PhotoInput:
    """Фото на входе провайдера."""
    content: bytes
    mime_type: str
    kind: str                     # overview | nameplate | context
    sha256: str


@dataclass(slots=True)
class OcrResult:
    """Результат OCR шильдика."""
    text: str = ""
    maker: str | None = None
    oem_number: str | None = None
    serial_number: str | None = None
    model_version: str = ""
    # 0..100 — насколько провайдер уверен в самом распознавании текста
    text_confidence: int = 0
    raw: dict = field(default_factory=dict)

    @property
    def is_readable(self) -> bool:
        """Считаем шильдик прочитанным, если есть номер или осмысленный текст.

        Без номера и с двумя символами текста идти дальше по OCR-ветке нельзя —
        это и есть сигнал переключиться на fallback.
        """
        return bool(self.oem_number) or len(self.text.strip()) >= 8


@dataclass(slots=True)
class VisionResult:
    """Результат визуальной категоризации (fallback-ветка)."""
    description: str = ""
    category: str | None = None
    maker: str | None = None
    model_version: str = ""
    confidence: int = 0
    raw: dict = field(default_factory=dict)


class ProviderUnavailable(RuntimeError):
    """Внешний сервис недоступен/исчерпал попытки.

    Отдельный тип нужен, чтобы конвейер отличал «сервис лежит» (скан можно
    переобработать позже, NFR-REL-02/03) от «распознали, но плохо».
    """


class OcrProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def recognize_text(self, photo: PhotoInput) -> OcrResult:
        ...


class VisionProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def describe(self, photos: list[PhotoInput]) -> VisionResult:
        ...
