# -*- coding: utf-8 -*-
"""Совфрахт Детали — точка входа FastAPI.

Шаг 1: каркас, аутентификация и роли (RBAC), модель данных (docs/07).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers

app = FastAPI(
    title="Совфрахт Детали — API",
    description="Распознавание судовых деталей по фото: закупка и оценка ремонта.",
    version="0.1.0",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=None,
)

# Фронтенд (Vite dev-сервер) ходит с другого origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": "sovfrasht-parts", "version": app.version, "docs": f"{settings.api_prefix}/docs"}
