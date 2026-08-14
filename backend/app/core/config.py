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

    # ── Пороги бизнес-логики ─────────────────────────────────────────────────
    # Ниже порога заявка автоматически не оформляется, скан уходит эксперту
    # (FR-REC-04, NFR-ACC-03).
    confidence_threshold: int = 70
    # Потолок доверия к fallback-ветке: шильдик не прочитан, опознан только тип
    # детали — такой результат обязан попасть на проверку человеку.
    vision_fallback_max_confidence: int = 55

    # ── Хранилище фото: MinIO / S3-совместимое (NFR-SEC-04) ──────────────────
    s3_endpoint_url: str = "http://minio:9000"
    s3_public_endpoint_url: str = ""      # адрес для подписанных ссылок наружу
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "scans"
    s3_region: str = "us-east-1"
    s3_presign_ttl_seconds: int = 900     # 15 минут — ссылка не должна жить вечно

    # ── Загрузка фото (NFR-SEC-04) ───────────────────────────────────────────
    max_photos_per_scan: int = 3          # FR-CAP-01
    max_photo_size_mb: int = 12
    allowed_photo_mime: str = "image/jpeg,image/png,image/heic,image/heif,image/webp"

    # ── Распознавание: провайдеры за адаптером (docs/06) ─────────────────────
    # Основной путь — OCR шильдика; fallback — облачная vision-модель.
    ocr_provider: str = "yandex"          # yandex | stub
    # openrouter — фронтир-модель зрения, основной определитель детали.
    # llm | stub оставлены: stub = выключено, конвейер деградирует мягко.
    vision_provider: str = "openrouter"

    yandex_ocr_url: str = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""

    vision_llm_url: str = ""
    vision_llm_api_key: str = ""
    vision_llm_model: str = ""

    # ── Спайк: сильная vision-модель как ОСНОВНОЙ определитель ───────────────
    # Каталог MVP узкий (57 позиций), и реальной детали в нём обычно нет: старый
    # путь отвечал «не найдено» вместо ответа по существу. Новый путь включается
    # флагом; ocr_first оставлен по умолчанию, чтобы прод не поехал.
    # По умолчанию vision_first: на демо подтвердилось, что каталог из 57 позиций
    # реальную деталь почти никогда не содержит, и прежний путь отвечал «не
    # найдено» вместо ответа по существу. ocr_first остаётся доступен флагом —
    # откатиться можно одной переменной, без правок кода.
    recognition_mode: str = "vision_first"   # vision_first | ocr_first

    # Потолок доверия к основному vision-пути. Он выше fallback-потолка (55):
    # там модель лишь угадывала тип по картинке, здесь — целенаправленно
    # опознаёт деталь и читает шильдик. Но 100 не даём: без сверки с каталогом
    # или экспертом абсолютной уверенности быть не может (NFR-ACC-03).
    vision_primary_max_confidence: int = 90

    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o"
    openrouter_max_tokens: int = 700
    # OpenRouter просит идентифицировать приложение — влияет на лимиты
    openrouter_referer: str = ""
    openrouter_title: str = "Sovfrasht Parts"

    # ── Надёжность внешних вызовов (NFR-REL-03) ──────────────────────────────
    external_timeout_seconds: float = 20.0
    external_max_attempts: int = 3
    external_backoff_seconds: float = 1.5

    # ── Поставщики и закупка (C1/C2, ADR-05) ─────────────────────────────────
    # curated — курируемый список в БД. Позже здесь появится api-провайдер
    # конкретного производителя; ядро при этом не меняется (FR-PRO-05).
    supplier_provider: str = "curated"
    # Пометка источника при заливке демо-предложений: их видно отдельно от API
    offers_default_source: str = "demo"

    # ── Сопоставление с каталогом (A3, FR-CAT-02) ────────────────────────────
    catalog_top_n: int = 5                # сколько кандидатов возвращаем
    catalog_trigram_threshold: float = 0.4  # порог similarity для pg_trgm
    catalog_min_prefix_len: int = 5       # короче — префиксный поиск даёт мусор
    # Вектор отключён сознательно: на узком каталоге хватает точного матча и
    # триграмм. Включать только если нечёткий поиск начнёт мазать.
    catalog_vector_search: bool = False

    # ── Контроль стоимости (NFR-COST-01) ─────────────────────────────────────
    vision_cache_enabled: bool = True
    vision_cache_ttl_days: int = 30
    max_image_side_px: int = 2000         # ужимаем перед отправкой — платим за меньший объём

    @property
    def allowed_photo_mime_set(self) -> set[str]:
        return {m.strip().lower() for m in self.allowed_photo_mime.split(",") if m.strip()}

    @property
    def max_photo_size_bytes(self) -> int:
        return self.max_photo_size_mb * 1024 * 1024

    @property
    def s3_presign_endpoint(self) -> str:
        """Внутри compose api ходит в minio:9000, а браузеру нужен внешний адрес."""
        return self.s3_public_endpoint_url or self.s3_endpoint_url

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
