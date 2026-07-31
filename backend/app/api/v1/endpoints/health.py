# -*- coding: utf-8 -*-
"""Проверка живости — для healthcheck контейнера и мониторинга."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(tags=["service"])


@router.get("/healthz", summary="Живость сервиса и доступность БД")
async def healthz(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
