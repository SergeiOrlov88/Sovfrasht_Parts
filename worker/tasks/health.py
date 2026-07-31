# -*- coding: utf-8 -*-
"""Проверочная задача: подтверждает, что очередь и воркер живы."""
from datetime import datetime, timezone

from worker.celery_app import celery_app


@celery_app.task(name="health.ping")
def ping() -> dict:
    return {"pong": True, "at": datetime.now(timezone.utc).isoformat()}
