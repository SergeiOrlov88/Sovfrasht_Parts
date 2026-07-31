# -*- coding: utf-8 -*-
"""Конфигурация приложения. Всё — из переменных окружения (NFR-MAINT-03),
секретов в коде нет (NFR-SEC-05)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Общее ────────────────────────────────────────────────────────────────
    app_env: str = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    postgres_user: str = "sovfrasht"
    postgres_password: str = ""
    postgres_db: str = "sovfrasht_parts"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Полный DSN можно задать явно — тогда он важнее составных частей
    # (используется в тестах: sqlite+aiosqlite://).
    database_url: str | None = None

    # ── Celery / Redis ───────────────────────────────────────────────────────
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # ── Токены (TTL вынесены в окружение по требованию заказчика) ────────────
    secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Хранится строкой через запятую, а НЕ list[str]: для сложных типов
    # pydantic-settings пытается разобрать значение переменной окружения как JSON
    # ещё до валидаторов и падает на «http://a,http://b». Разбираем сами — см.
    # cors_origin_list.
    cors_origins: str = "http://localhost:5173"

    # ── Пороги бизнес-логики (задел на шаги 2-3) ─────────────────────────────
    confidence_threshold: int = 70

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS задаётся строкой через запятую."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # В проде пустой SECRET_KEY недопустим: иначе токены подделываются тривиально.
    if s.is_production and not s.secret_key:
        raise RuntimeError("SECRET_KEY обязателен в окружении prod (NFR-SEC-05)")
    return s


settings = get_settings()
