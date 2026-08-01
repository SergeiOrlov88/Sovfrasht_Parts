# 07 · Модель данных

Логическая модель данных продукта **Совфрахт Детали**. Диаграмма «сущность-связь» (Mermaid `erDiagram`) плюс описание сущностей и правил. Служит основой для схемы БД (PostgreSQL) и миграций.

## 1. ER-диаграмма

```mermaid
erDiagram
    ORGANIZATION ||--o{ VESSEL : "владеет"
    ORGANIZATION ||--o{ USER : "включает"
    VESSEL ||--o{ SCAN : "источник"
    USER ||--o{ SCAN : "создаёт"
    SCAN ||--o{ PHOTO : "содержит"
    SCAN ||--o| RECOGNITION : "даёт"
    RECOGNITION }o--o| PART : "определяет"
    RECOGNITION ||--o{ RECOGNITION_CANDIDATE : "предлагает"
    RECOGNITION_CANDIDATE }o--|| PART : "ссылается"
    RECOGNITION ||--o| MODERATION_TASK : "может требовать"
    USER ||--o{ MODERATION_TASK : "эксперт решает"
    PART ||--o{ PART_ALTERNATIVE : "имеет аналоги"
    PART_ALTERNATIVE }o--|| PART : "аналог"
    PART ||--o{ SUPPLIER_OFFER : "продаётся как"
    SUPPLIER ||--o{ SUPPLIER_OFFER : "предлагает"
    PART ||--o| REPAIR_INFO : "ремонтопригодность"
    RECOGNITION ||--o{ PART_REQUEST : "порождает"
    PART_REQUEST }o--|| PART : "на деталь"
    PART_REQUEST }o--|| VESSEL : "для судна"
    PART_REQUEST }o--|| USER : "автор"
    RECOGNITION ||--o{ TRAINING_SAMPLE : "накапливает"

    ORGANIZATION {
        uuid id PK
        string name
        string type "владелец/верфь"
    }
    VESSEL {
        uuid id PK
        uuid organization_id FK
        string name
        string imo "номер IMO"
        string type
    }
    USER {
        uuid id PK
        uuid organization_id FK
        string login
        string full_name
        string role "mechanic/supplier_manager/fleet_owner/expert/admin"
        string password_hash
    }
    SCAN {
        uuid id PK
        uuid vessel_id FK
        uuid author_id FK
        string status "queued/processing/done/needs_review/error"
        float geo_lat "nullable"
        float geo_lon "nullable"
        datetime created_at
    }
    PHOTO {
        uuid id PK
        uuid scan_id FK
        string storage_key
        string kind "overview/nameplate/context"
        int width
        int height
    }
    RECOGNITION {
        uuid id PK
        uuid scan_id FK
        uuid part_id FK "nullable до подтверждения"
        int confidence "0-100"
        string ocr_text "считанная маркировка"
        string maker_detected
        string oem_detected
        string model_version
        string status "auto/confirmed/corrected/rejected"
        datetime created_at
    }
    RECOGNITION_CANDIDATE {
        uuid id PK
        uuid recognition_id FK
        uuid part_id FK
        float relevance "0-1"
    }
    PART {
        uuid id PK
        string impa_code "nullable"
        string issa_code "nullable"
        string oem_number "nullable"
        string maker
        string name
        string category
        json specs
        string equipment "применимое оборудование"
    }
    PART_ALTERNATIVE {
        uuid id PK
        uuid part_id FK
        uuid alt_part_id FK
        string compatibility "full/partial/kit"
        string note
    }
    SUPPLIER {
        uuid id PK
        string name
        string type "площадка/поставщик/OEM"
        string url
        string region
    }
    SUPPLIER_OFFER {
        uuid id PK
        uuid part_id FK
        uuid supplier_id FK
        string price "демо/справочно на MVP"
        string lead_time
        string stock_status "in/low/out"
        string deep_link
    }
    REPAIR_INFO {
        uuid id PK
        uuid part_id FK
        string verdict "repair/replace"
        string rationale
        string repair_cost_estimate
        string replace_cost_estimate
        string repair_time
    }
    PART_REQUEST {
        uuid id PK
        uuid recognition_id FK
        uuid part_id FK
        uuid vessel_id FK
        uuid author_id FK
        int quantity
        string priority "low/normal/urgent"
        string status "new/in_review/approved/rejected/ordered/received"
        string comment
        datetime created_at
    }
    MODERATION_TASK {
        uuid id PK
        uuid recognition_id FK
        uuid expert_id FK "nullable до взятия в работу"
        string status "pending/in_progress/resolved"
        string resolution "confirmed/corrected/rejected"
        uuid corrected_part_id FK "nullable"
        datetime created_at
        datetime resolved_at
    }
    TRAINING_SAMPLE {
        uuid id PK
        uuid recognition_id FK
        uuid photo_id FK
        uuid correct_part_id FK
        string source "user_feedback/expert"
        datetime created_at
    }
```

## 2. Описание ключевых сущностей

**Organization** — компания (Совфрахт как основной арендатор; в перспективе — внешние организации). Тип различает владельца флота и верфь.

**Vessel** — судно, с номером IMO. Механик привязан к судну; сканы и заявки относятся к судну.

**User** — пользователь с ролью (RBAC из NFR-SEC-03). Принадлежит организации.

**Scan** — единица распознавания: набор фото + метаданные. Проходит статусы `queued → processing → done | needs_review | error`.

**Photo** — отдельное фото скана с типом (общий вид / шильдик / место установки) и ключом в хранилище (доступ по подписанным ссылкам, NFR-SEC-04).

**Recognition** — результат распознавания скана: определённая деталь (или null до подтверждения), `confidence`, считанный OCR-текст, обнаруженные производитель/номер, версия модели, статус.

**RecognitionCandidate** — альтернативные кандидаты детали с релевантностью (реализует бизнес-правило «минимум один альтернативный вариант», NFR-ACC-02).

**Part** — позиция каталога: коды IMPA/ISSA/OEM, производитель, наименование, категория, характеристики (json), применимое оборудование. Хотя бы один из кодов/номеров заполнен.

**PartAlternative** — связь «деталь ↔ аналог» с признаком совместимости.

**Supplier / SupplierOffer** — поставщик/площадка и его предложение по детали (цена, срок, наличие, deep-link). На MVP цены справочные/курируемые.

**RepairInfo** — ремонтопригодность детали: вердикт (ремонт/замена), обоснование, оценки стоимости и срока.

**PartRequest** — заявка на снабжение из отчёта. Проходит статусы `new → in_review → approved | rejected → ordered → received`.

**ModerationTask** — задача HITL: создаётся при `confidence` ниже порога или вручную; эксперт подтверждает/исправляет/отклоняет.

**TrainingSample** — размеченный пример (из обратной связи пользователя или решения эксперта) для дообучения модели (FR-REC-06).

**VisionCache** *(добавлено на шаге 2 реализации)* — кэш ответов платных vision/OCR API. Ключ — пара «провайдер + sha256 изображения», плюс версия модели, тело ответа и счётчик попаданий. Нужен для NFR-COST-01: одно и то же фото не оплачивается дважды — ни при повторной отправке скана, ни при переобработке после сбоя. Записи старше `VISION_CACHE_TTL_DAYS` считаются промахом (модели обновляются). По счётчику попаданий видно, сколько платных вызовов сэкономлено.

**PartAlias** *(добавлено на шаге 3)* — альтернативное написание номера или наименования. Ищется точно, наравне с основным номером: поставщики пишут один и тот же номер по-разному, и это дешевле и надёжнее нечёткого поиска.

У **Part** на шаге 3 добавлены нормализованные коды `impa_code_norm`, `issa_code_norm`, `oem_number_norm`, `maker_norm` — канонические формы (верхний регистр, только A-Z0-9). Заполняются одинаково при импорте каталога и при поиске по строке из OCR, иначе точное совпадение промахивается на пробелах и дефисах.

У **Recognition** на шаге 3 добавлены `detected_tokens` (все номероподобные токены с шильдика и признак выбранного — сырьё для калибровки эвристики по реальным фото) и `catalog_status` (`matched` / `candidates` / `not_found`).

У **Recognition** на шаге 4 добавлены поля обратной связи (FR-REP-04): `feedback_verdict` (`confirm`/`reject`), `feedback_by`, `feedback_at`, `feedback_comment`.

У **Photo** на шаге 2 добавлены поля: `mime_type`, `size_bytes` и `content_sha256` — хеш содержимого служит ключом кэша выше и позволяет распознать повторную присылку того же изображения.

## 3. Правила целостности и данных

Каждый `Scan` принадлежит одному судну и одному автору; данные видны в пределах организации (RBAC). **Инвариант опознаваемости `Part`:** обязательны `name` И хотя бы одно из `maker` / `equipment` (CHECK `ck_parts_identifiable`, миграция `0005`). Жёсткое требование «минимум один код» снято миграцией `0004`: в стартовом каталоге 30 из 56 позиций (крупные судовые дизели Wärtsilä, MAN B&W) поставляются без публичных номеров и опознаются по `name` + `maker` + `equipment`. Коды `impa_code`/`issa_code`/`oem_number` желательны, но не обязательны; совсем неопознаваемых строк в каталоге быть не должно. `Recognition.part_id` может быть null до подтверждения; после подтверждения/исправления заполняется. `PartRequest` не создаётся автоматически при `confidence` ниже порога без подтверждения (FR-REC-04, NFR-ACC-03). Удаление пользователя не удаляет его сканы/заявки (историчность) — используется мягкое удаление/анонимизация. Все временные метки — в UTC; отображение — в часовом поясе пользователя.

## 4. Индексы и поиск (рекомендации для реализации)

Индексы по внешним ключам (`vessel_id`, `author_id`, `scan_id`, `part_id`) и по статусам (`Scan.status`, `PartRequest.status`, `ModerationTask.status`) для реестров и очередей. Полнотекстовый/триграммный индекс по `Part.name`, `oem_number`, кодам — для быстрого поиска. Векторный индекс (pgvector) по эмбеддингам описаний деталей — для нечёткого сопоставления результата распознавания с каталогом (FR-CAT-02).
