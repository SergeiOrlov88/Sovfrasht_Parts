# -*- coding: utf-8 -*-
"""Хранилище фото: MinIO / S3-совместимое (docs/06).

Доступ к файлам — только по подписанным ссылкам с истечением (NFR-SEC-04);
бакет наружу не публикуется. boto3 синхронный, поэтому вызовы уводим в threadpool,
чтобы не блокировать событийный цикл.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Ошибка хранилища — отделяем от ошибок распознавания."""


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


@lru_cache
def _internal_client():
    """Клиент для записи/чтения внутри сети compose."""
    return _client(settings.s3_endpoint_url)


@lru_cache
def _presign_client():
    """Отдельный клиент для подписи: ссылка должна вести на внешний адрес,
    иначе браузер пойдёт в http://minio:9000, которого у него нет."""
    return _client(settings.s3_presign_endpoint)


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_storage_key(scan_id: uuid.UUID, kind: str, filename: str) -> str:
    """Ключ вида <scan_id>/<kind>-<uuid>.<ext>. Префикс бакета не дублируем —
    бакет уже называется scans, иначе путь выходит scans/scans/..."""
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    return f"{scan_id}/{kind}-{uuid.uuid4().hex}{suffix[:10]}"


def _ensure_bucket_sync() -> None:
    client = _internal_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        try:
            client.create_bucket(Bucket=settings.s3_bucket)
            logger.info("Создан бакет %s", settings.s3_bucket)
        except ClientError as exc:                     # гонка при параллельном старте
            if (exc.response.get("Error", {}).get("Code")
                    not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}):
                raise


async def ensure_bucket() -> None:
    await run_in_threadpool(_ensure_bucket_sync)


def _put_sync(key: str, content: bytes, content_type: str) -> None:
    _internal_client().put_object(
        Bucket=settings.s3_bucket, Key=key, Body=content, ContentType=content_type
    )


async def put_object(key: str, content: bytes, content_type: str) -> None:
    try:
        await run_in_threadpool(_put_sync, key, content, content_type)
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Не удалось сохранить файл: {exc}") from exc


def get_object_sync(key: str) -> bytes:
    """Синхронное чтение — используется воркером (он и так вне цикла событий)."""
    try:
        return _internal_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Не удалось прочитать файл {key}: {exc}") from exc


def _presign_sync(key: str, ttl: int) -> str:
    return _presign_client().generate_presigned_url(
        "get_object", Params={"Bucket": settings.s3_bucket, "Key": key}, ExpiresIn=ttl
    )


async def presigned_url(key: str, ttl: int | None = None) -> str:
    """Временная ссылка на фото (NFR-SEC-04)."""
    ttl = ttl or settings.s3_presign_ttl_seconds
    try:
        return await run_in_threadpool(_presign_sync, key, ttl)
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Не удалось подписать ссылку: {exc}") from exc
