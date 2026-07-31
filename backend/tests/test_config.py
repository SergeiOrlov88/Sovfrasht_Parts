# -*- coding: utf-8 -*-
"""Разбор конфигурации из переменных окружения (NFR-MAINT-03).

Регрессия: раньше cors_origins был list[str], и pydantic-settings пытался
разобрать значение переменной окружения как JSON ещё до валидаторов — контейнер
падал на старте при CORS_ORIGINS='http://a,http://b'. Юнит-тесты этого не ловили,
потому что не выставляли переменную и брали значение по умолчанию.
"""
import pytest

from app.core.config import Settings


def _settings(monkeypatch, **env) -> Settings:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # _env_file=None: берём только переменные окружения, без чтения .env с диска
    return Settings(_env_file=None)


def test_cors_origins_from_env_comma_separated(monkeypatch):
    s = _settings(monkeypatch, CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173")
    assert s.cors_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_single_value(monkeypatch):
    s = _settings(monkeypatch, CORS_ORIGINS="https://parts.example.ru")
    assert s.cors_origin_list == ["https://parts.example.ru"]


def test_cors_origins_tolerates_spaces_and_trailing_comma(monkeypatch):
    s = _settings(monkeypatch, CORS_ORIGINS=" http://a , http://b , ")
    assert s.cors_origin_list == ["http://a", "http://b"]


def test_token_ttl_from_env(monkeypatch):
    """TTL токенов задаётся окружением — требование заказчика."""
    s = _settings(monkeypatch, ACCESS_TOKEN_TTL_MINUTES="5", REFRESH_TOKEN_TTL_DAYS="3")
    assert s.access_token_ttl_minutes == 5
    assert s.refresh_token_ttl_days == 3


def test_dsn_built_from_parts(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = _settings(
        monkeypatch,
        POSTGRES_USER="u", POSTGRES_PASSWORD="p", POSTGRES_DB="d",
        POSTGRES_HOST="h", POSTGRES_PORT="5432",
    )
    assert s.sqlalchemy_dsn == "postgresql+asyncpg://u:p@h:5432/d"


def test_explicit_database_url_wins(monkeypatch):
    s = _settings(monkeypatch, DATABASE_URL="sqlite+aiosqlite:///./x.db", POSTGRES_USER="u")
    assert s.sqlalchemy_dsn == "sqlite+aiosqlite:///./x.db"


def test_prod_requires_secret_key(monkeypatch):
    """В prod пустой SECRET_KEY недопустим (NFR-SEC-05)."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        get_settings()
    get_settings.cache_clear()
