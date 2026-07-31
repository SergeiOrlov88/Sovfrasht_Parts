# Единый образ для api и worker: доменный код (модели, сервисы) живёт в backend
# и импортируется воркером — дублирования нет. Контекст сборки — корень репозитория.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv

WORKDIR /srv

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

# Зависимости ставим отдельным слоем — он кэшируется и не пересобирается при правке кода
COPY backend/pyproject.toml /srv/backend/pyproject.toml
RUN pip install --upgrade pip && pip install -e /srv/backend

COPY backend /srv/backend
COPY worker /srv/worker

WORKDIR /srv/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
