# -*- coding: utf-8 -*-
"""Celery-задача распознавания скана (A2).

Внешние сервисы могут лежать — тогда задача повторяется с backoff, а скан
остаётся доступным для переобработки (NFR-REL-02, NFR-REL-03).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.adapters.vision.base import ProviderUnavailable
from app.core.database import SessionLocal, engine
from app.services import recognition_service
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run(scan_id: uuid.UUID) -> dict:
    """Обработка одного скана.

    Celery на каждую задачу вызывает asyncio.run(), то есть создаёт НОВЫЙ цикл
    событий. Пул asyncpg привязан к тому циклу, в котором соединение открылось,
    и переиспользование пула во втором цикле даёт «Future attached to a different
    loop»: первая задача после старта воркера проходит, все следующие падают.
    Поэтому в конце задачи пул закрываем — следующая откроет соединения в своём
    цикле. Стоимость — одно новое подключение к БД на скан, это несопоставимо
    дешевле распознавания.
    """
    try:
        async with SessionLocal() as db:
            try:
                outcome = await recognition_service.run_pipeline(db, scan_id)
            except ProviderUnavailable:
                await recognition_service.mark_error(db, scan_id)
                raise
            except Exception:
                await recognition_service.mark_error(db, scan_id)
                raise
    finally:
        await engine.dispose()
    return {
        "scan_id": str(scan_id),
        "status": outcome.scan_status.value,
        "confidence": outcome.confidence,
        "model_version": outcome.model_version,
        "needs_expert": outcome.needs_expert,
        "used_fallback": outcome.used_fallback,
        "cache_hits": outcome.cache_hits,
    }


@celery_app.task(
    name="recognition.process_scan",
    bind=True,
    max_retries=3,
    autoretry_for=(ProviderUnavailable,),   # повторяем только сбои внешних сервисов
    retry_backoff=True,                     # экспоненциальная пауза между попытками
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_scan(self, scan_id: str) -> dict:
    logger.info("Распознавание скана %s (попытка %d)", scan_id, self.request.retries + 1)
    return asyncio.run(_run(uuid.UUID(scan_id)))
