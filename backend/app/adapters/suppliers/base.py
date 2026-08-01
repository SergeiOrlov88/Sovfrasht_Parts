# -*- coding: utf-8 -*-
"""Единый интерфейс поставщиков предложений (ADR-05 в docs/06).

Ядро не знает, откуда взялось предложение: из курируемого списка в БД или из
внешнего API производителя. Это тот же приём, что и с адаптерами vision/OCR —
`ApiProvider` под конкретного производителя встанет рядом с `CuratedProvider`
без правок сервисного слоя (FR-PRO-05, следующий этап).
"""
from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SupplierInfo:
    name: str
    type: str                       # marketplace | supplier | oem | reman
    url: str | None = None
    region: str | None = None


@dataclass(slots=True)
class Offer:
    """Предложение по детали. Цены на MVP справочные (source=demo/curated)."""
    supplier: SupplierInfo
    price: str | None = None
    lead_time: str | None = None
    stock_status: str | None = None      # in | low | out
    deep_link: str | None = None
    source: str = "curated"
    fetched_at: datetime | None = None
    # id позиции каталога, к которой относится предложение: у аналогов он свой
    part_id: uuid.UUID | None = None
    external_id: str | None = None       # идентификатор на стороне поставщика
    raw: dict = field(default_factory=dict)


class SupplierUnavailable(RuntimeError):
    """Источник предложений недоступен.

    Отдельный тип, чтобы отчёт мог показать «цены временно недоступны» вместо
    ошибки — вкладка «Закупка» не должна ронять весь отчёт (NFR-REL-03).
    """


class SupplierProvider(abc.ABC):
    """Источник предложений по детали."""

    name: str = "base"

    @abc.abstractmethod
    async def get_offers(self, part) -> list[Offer]:
        """Предложения по конкретной позиции каталога.

        Реализация обязана возвращать пустой список, если предложений нет,
        и бросать SupplierUnavailable, если источник недоступен.
        """
