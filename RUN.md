# Запуск приложения локально

Два пути. **Основной — через Docker**: так же, как поедет на сервер.
**Запасной — без Docker**: если Docker не установлен, приложение всё равно
поднимается на локальном Python и SQLite.

---

## Путь 1. Через Docker (рекомендуется)

Нужен Docker и Docker Compose.

### 1. Конфигурация

```bash
cp .env.example .env
```

В `.env` задайте два значения (остальное можно оставить как есть):

```bash
# длинный случайный ключ подписи токенов
python -c "import secrets; print(secrets.token_urlsafe(64))"
# -> вставьте в SECRET_KEY=

# пароли БД и хранилища — любые непустые
POSTGRES_PASSWORD=...
S3_SECRET_KEY=...
```

### 2. Поднять стек

```bash
docker compose up -d --build
```

Поднимутся пять сервисов. Миграции накатываются автоматически при старте `api`.

| сервис | порт | назначение |
|---|---|---|
| postgres | 5434 | БД (pgvector) |
| redis | 6381 | брокер очереди |
| minio | 9010 / 9011 | хранилище фото / веб-консоль |
| api | 8010 | REST API |
| worker | — | распознавание в фоне |

### 3. Демо-данные

**Порядок важен:** офферы привязываются к деталям по OEM-номеру, а правила
ремонта — к позициям каталога, поэтому каталог заливается первым.

```bash
docker compose exec api python -m app.seed                                    # 1. организация, суда, пользователи
docker compose exec api python -m app.catalog_import ../seed/catalog_seed.csv # 2. каталог
docker compose exec api python -m app.offers_import ../seed/offers_seed.csv   # 3. предложения поставщиков
docker compose exec api python -m app.repair_import ../seed/repair_rules_seed.csv  # 4. правила ремонта
```

Все сидеры идемпотентны: повторный запуск обновляет данные, а не плодит дубли.
У каждого есть `--dry-run` — проверить файл, ничего не записывая.

### 4. Фронтенд

```bash
cd frontend
npm install
npm run dev
```

### 5. Проверка

| адрес | что это |
|---|---|
| http://localhost:5173 | приложение |
| http://localhost:8010/api/v1/healthz | живость API и БД |
| http://localhost:8010/api/v1/docs | Swagger UI |
| http://localhost:9011 | консоль MinIO |

Если `http://localhost:5173` не открывается: Vite по умолчанию поднимается
только на IPv6 (`::1`). В `vite.config.js` привязка задана явно
(`host: '127.0.0.1'`), но при своей конфигурации можно запустить с флагом:
`npm run dev -- --host 127.0.0.1`.

Остановить: `docker compose down` (с данными: `docker compose down -v`).

---

## Путь 2. Без Docker

Работает всё, кроме загрузки фото: она требует MinIO. Отчёты, каталог, закупка,
ремонт и панель эксперта доступны полностью.

### 1. Бэкенд

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # Linux/macOS: .venv/bin/pip
```

Переменные окружения (SQLite вместо Postgres):

```bash
export DATABASE_URL="sqlite+aiosqlite:///./local.db"
export SECRET_KEY="любая-длинная-случайная-строка"
export APP_ENV=local
export CORS_ORIGINS=http://localhost:5173
```

Миграции и данные:

```bash
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.seed
.venv/Scripts/python -m app.catalog_import ../seed/catalog_seed.csv
.venv/Scripts/python -m app.offers_import ../seed/offers_seed.csv
.venv/Scripts/python -m app.repair_import ../seed/repair_rules_seed.csv
```

Запуск:

```bash
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### 2. Фронтенд

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, /api проксируется на 8010
```

### Ограничения этого пути

- **Загрузка фото не работает** — она требует MinIO. Всё остальное (каталог,
  отчёт, закупка, ремонт, панель эксперта) доступно полностью.
- **Очередь Celery не работает** без Redis — распознавание в фоне не запустится.
- Чтобы было что открыть в интерфейсе, заведите демо-сканы напрямую в БД или
  поднимите полный стек по пути 1.

---

## Демо-пользователи

Создаются `python -m app.seed`. Пароль у всех — `demo12345`
(значение можно переопределить переменной `SEED_PASSWORD`).

| логин | роль | что видит |
|---|---|---|
| `mechanic` | механик | сканы и заявки своих судов |
| `supply` | снабженец | все заявки организации, маршрут статусов |
| `owner` | судовладелец | все заявки организации |
| `expert` | эксперт | очередь модерации |
| `admin` | администратор | пользователи, суда, очередь модерации |

**Это данные только для локальной разработки.** Сидер отказывается работать при
`APP_ENV=prod`.

---

## Тесты

```bash
cd backend
.venv/Scripts/python -m pytest
```

Тесты идут на SQLite — поднимать Postgres не нужно.
