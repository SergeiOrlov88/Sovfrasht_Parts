# -*- coding: utf-8 -*-
"""Подключение к БД: async engine, фабрика сессий, зависимость get_db."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Базовый класс моделей."""


def _engine_kwargs() -> dict:
    # SQLite (тесты) не понимает пул-настройки Postgres
    if settings.sqlalchemy_dsn.startswith("sqlite"):
        return {"echo": False}
    return {"echo": False, "pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


engine = create_async_engine(settings.sqlalchemy_dsn, **_engine_kwargs())

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
