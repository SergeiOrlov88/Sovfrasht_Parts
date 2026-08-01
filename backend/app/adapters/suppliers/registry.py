# -*- coding: utf-8 -*-
"""Выбор источника предложений. Смена провайдера — правка .env, не кода (ADR-05)."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.suppliers.base import SupplierProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_supplier_provider(db: AsyncSession) -> SupplierProvider:
    """Пока реализация одна. Когда появится API производителя, здесь встанет
    ветка `api` — сервисный слой при этом не меняется (FR-PRO-05)."""
    if settings.supplier_provider != "curated":
        logger.warning("SUPPLIER_PROVIDER=%s пока не реализован — курируемый список",
                       settings.supplier_provider)
    from app.adapters.suppliers.curated import CuratedProvider
    return CuratedProvider(db)
