# Совфрахт Детали

Приложение для распознавания судовых деталей по фотографии с рекомендациями по закупке
и оценке ремонта. Внутренний инструмент компании, self-hosted.

Вся аналитика — в [`docs/`](docs/README.md); контекст для Claude Code — в [`CLAUDE.md`](CLAUDE.md).

## Состояние

**Шаг 1 из «Порядка реализации» (`docs/03`) — готов:** каркас, аутентификация и роли (RBAC),
модель данных из `docs/07`. Конвейер распознавания — шаг 2.

## Стек

Python + FastAPI · PostgreSQL 16 (+pgvector) · Celery + Redis · React + Vite (PWA) · Docker.

## Локальный запуск

Нужен Docker и Docker Compose.

```bash
cp .env.example .env
# задайте SECRET_KEY:  python -c "import secrets; print(secrets.token_urlsafe(64))"
docker compose up -d --build
```

Поднимутся `postgres` (порт 5434), `redis` (6381), `api` (8010) и `worker`.
Миграции накатываются автоматически при старте `api`.

| адрес | что это |
|---|---|
| http://localhost:8010/api/v1/docs | Swagger UI |
| http://localhost:8010/api/v1/healthz | проверка живости |

Демо-данные (организация, суда, по пользователю на каждую роль):

```bash
docker compose exec api python -m app.seed
```

Логины: `admin`, `mechanic`, `supply`, `owner`, `expert` — пароль у всех `demo12345`
(только для локальной разработки).

### Фронтенд

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, запросы /api проксируются на 8010
```

На шаге 1 реализован только экран входа.

## Тесты

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Тесты идут на SQLite — поднимать Postgres не нужно. Покрыты вход, жизненный цикл токенов,
разграничение по ролям и изоляция организаций (NFR-SEC-02, NFR-SEC-03, NFR-MAINT-02).

## Структура

```
backend/    FastAPI: модели, схемы, сервисы, API, миграции (Alembic)
worker/     Celery: точка входа и задачи; образ общий с backend
frontend/   React + Vite + PWA
docs/       аналитика — источник истины
openapi.yaml  контракт API, генерируется из FastAPI
```

## Соглашения

Секреты — только в переменных окружения (NFR-SEC-05). Время в БД — UTC.
Каждый эндпоинт проверяет роль и принадлежность к организации (NFR-SEC-03).
При изменении API обновляется `openapi.yaml`.
