# 08 · Контракты API и спецификация интеграций

REST API продукта **Совфрахт Детали** и описание внешних интеграций. Стиль: REST/JSON, аутентификация по Bearer-токену (JWT), версионирование через префикс `/api/v1`. Все ответы — JSON; ошибки — по единой схеме. Эндпоинты реализуют функциональные требования из док 04 (ссылки в скобках).

## 1. Общие соглашения

Базовый путь: `/api/v1`. Аутентификация: заголовок `Authorization: Bearer <token>`. Формат времени: ISO 8601, UTC. Идентификаторы: UUID. Пагинация: `?page=&page_size=` (по умолчанию 20). Ошибки — единый формат:

```json
{ "error": { "code": "validation_error", "message": "Описание", "details": {} } }
```

Коды статусов: 200 OK, 201 Created, 202 Accepted (задача принята в обработку), 400, 401, 403, 404, 409 (конфликт/идемпотентность), 422 (валидация), 500.

RBAC: каждый эндпоинт проверяет роль и принадлежность к организации/судну (NFR-SEC-03). Ниже в скобках — допустимые роли.

## 2. Аутентификация (AUTH)

`POST /auth/login` — вход. Body: `{ "login", "password" }` → `{ "access_token", "refresh_token", "user": {...} }`. (FR-AUTH-01)

`POST /auth/refresh` — обновление токена. Body: `{ "refresh_token" }` → новый `access_token`.

`GET /auth/me` — текущий пользователь и роль. (все авторизованные)

## 3. Пользователи и суда (ADMIN)

`GET /users` / `POST /users` / `PATCH /users/{id}` — управление пользователями. (admin) (FR-AUTH-04)

`GET /vessels` / `POST /vessels` / `PATCH /vessels/{id}` — суда организации. (admin, fleet_owner)

## 4. Сканы и распознавание (CAPTURE, RECOGNITION)

`POST /scans` — создать скан и запустить распознавание. (mechanic, supplier_manager)
Multipart: до 3 файлов `photos[]` + JSON-часть `{ "vessel_id", "geo?": {lat,lon}, "client_scan_id" }`.
`client_scan_id` — клиентский идентификатор для идемпотентности (NFR-REL-04): повторная отправка с тем же значением возвращает существующий скан.
Ответ `202`: `{ "scan_id", "status": "processing" }`. (FR-CAP-01, FR-CAP-04, FR-REC-01)

`GET /scans/{id}` — статус и данные скана: `{ "id", "status", "created_at", "photos": [...] }`. (автор, роли организации)

`GET /scans/{id}/report` — полный отчёт по завершённому скану. (FR-REP-01)
```json
{
  "scan_id": "...",
  "status": "done",
  "recognition": {
    "confidence": 94,
    "ocr_text": "W-32 / 148821",
    "part": {
      "id": "...", "name": "Топливная форсунка (инжектор)",
      "impa_code": "593512", "issa_code": "75.301.12",
      "oem_number": "148821", "maker": "Wärtsilä",
      "equipment": "Wärtsilä 6L32", "specs": {...}
    },
    "candidates": [ { "part_id": "...", "name": "...", "relevance": 0.72 } ],
    "needs_review": false
  },
  "alternatives": [ { "part_id": "...", "name": "...", "compatibility": "full" } ],
  "offers": [ { "supplier": "ShipServ", "price": "$1240", "lead_time": "7-10 дн", "stock_status": "in", "deep_link": "https://..." } ],
  "repair": { "verdict": "replace", "rationale": "...", "replace_cost_estimate": "$1240", "repair_cost_estimate": "$690", "repair_time": "5-8 дн" }
}
```

`GET /scans` — список сканов (реестр) с фильтрами `?vessel_id=&status=&from=&to=`. (роли организации) (FR-REG-01)

`POST /scans/{id}/feedback` — подтверждение/исправление результата. Body: `{ "verdict": "confirm" | "reject", "correct_part_id?": "..." }` → сохраняет обратную связь и `TrainingSample`. (FR-REP-04, FR-REC-06)

`POST /scans/{id}/send-to-expert` — отправить на модерацию. → создаёт `ModerationTask`. (FR-HITL-01)

## 5. Каталог деталей (CATALOG)

`GET /parts/{id}` — карточка детали. (все авторизованные)

`GET /parts?query=&code=&category=` — поиск по каталогу (по коду/номеру/названию). (FR-CAT-02)

`GET /parts/{id}/alternatives` — аналоги. (FR-CAT-04)

`POST /parts` / `PATCH /parts/{id}` — ведение справочника. (admin, expert) (FR-CAT-05)

## 6. Закупка (PROCUREMENT)

`GET /parts/{id}/offers` — предложения поставщиков по детали. (FR-PRO-01)

`POST /part-requests` — создать заявку на снабжение. Body: `{ "recognition_id", "part_id", "vessel_id", "quantity", "priority", "comment?" }` → `201 { "id", "status": "new" }`. (FR-PRO-03)

`GET /part-requests?vessel_id=&status=` — реестр заявок. (supplier_manager, fleet_owner) (FR-PRO-04, FR-REG-01)

`PATCH /part-requests/{id}` — смена статуса. Body: `{ "status": "in_review|approved|rejected|ordered|received", "comment?" }`. (supplier_manager, fleet_owner) (FR-REG-02)

## 7. Ремонт (REPAIR)

`GET /parts/{id}/repair` — рекомендация «ремонт/замена» и сравнение. (FR-REPAIR-01)

`GET /parts/{id}/repair-services` — сервисы/верфи для ремонта (курируемый список). (FR-REPAIR-03)

## 8. Модерация / HITL (EXPERT)

`GET /moderation/tasks?status=pending` — очередь задач эксперта. (expert) (FR-HITL-02)

`POST /moderation/tasks/{id}/claim` — взять задачу в работу. (expert)

`POST /moderation/tasks/{id}/resolve` — решение. Body: `{ "resolution": "confirmed|corrected|rejected", "correct_part_id?": "..." }` → обновляет `Recognition`, уведомляет автора, сохраняет `TrainingSample`. (FR-HITL-03)

## 9. Уведомления (NOTIFY)

`GET /notifications` — список уведомлений пользователя. `POST /notifications/{id}/read` — отметить прочитанным. (FR-NOT-01)
Канал доставки MVP: внутри приложения + email. Пуш — на нативном этапе.

## 10. Внешние интеграции

**Vision/OCR API (за адаптером).** Worker вызывает внешнюю модель для (а) описания/категоризации детали, (б) OCR маркировки. Интерфейс адаптера: `recognize(photos) -> { category, ocr_text, maker, oem, raw }`. Требования: таймауты, retry с backoff, graceful-деградация при недоступности (NFR-REL-03), логирование версии модели (FR-REC-05), контроль стоимости и кэширование по идентичным сканам (NFR-COST-01). Провайдер сменяем без изменения ядра.

**Каталоги IMPA/ISSA/OEM.** Импортируются в локальный справочник `Part` (ETL/парсинг/лицензия). На MVP — узкая категория. Обновление — периодический импорт. Прямого рантайм-вызова внешнего каталога на MVP нет (данные локальны).

**Площадки/поставщики (ShipServ и др.).** На MVP — курируемый справочник `Supplier`/`SupplierOffer` с deep-ссылками и справочными ценами. Прямые API прайсов/наличия и оформление заказа — за пределами MVP (FR-PRO-05), закладывается в модель для будущего.

## 11. Идемпотентность и надёжность

Создание скана и заявки поддерживает идемпотентность через клиентский идентификатор (`client_scan_id` / `Idempotency-Key` заголовок) — повтор не создаёт дубликатов (NFR-REL-04). Тяжёлые операции (распознавание) асинхронны: клиент получает `202` и опрашивает `GET /scans/{id}` или получает уведомление. Ошибки распознавания оставляют скан в статусе `error` с возможностью переобработки (NFR-REL-02).

## 12. OpenAPI

Полная спецификация ведётся как `openapi.yaml` в репозитории и генерируется/проверяется автоматически (FastAPI отдаёт схему из кода). Этот документ — контракт верхнего уровня; поля и коды синхронизируются с `openapi.yaml`.
