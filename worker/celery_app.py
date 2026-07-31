# -*- coding: utf-8 -*-
"""Celery-приложение. Собирается из того же образа, что и api, и импортирует
доменный код из backend — дублирования моделей и сервисов нет.

На шаге 1 задач распознавания ещё нет: есть только ping для проверки, что связка
api → redis → worker поднимается. Конвейер распознавания — шаг 2 (A2).
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "sovfrasht_parts",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks.health", "worker.tasks.recognition"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",                       # время в UTC (docs/07 §3)
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_acks_late=True,                  # задача переедет на другой воркер, если этот упадёт
    worker_prefetch_multiplier=1,
)
