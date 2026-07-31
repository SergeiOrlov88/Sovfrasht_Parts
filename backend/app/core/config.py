# -*- coding: utf-8 -*-
"""Конфигурация приложения. Всё — из переменных окружения (NFR-MAINT-03),
секретов в коде нет (NFR-SEC-05)."""
from functools import lru_cache

from pydantic import Field, field_validator
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
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # ── Пороги бизнес-логики (задел на шаги 2-3) ─────────────────────────────
    confidence_threshold: int = 70

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        """CORS_ORIGINS приходит строкой через запятую."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

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
