# -*- coding: utf-8 -*-
"""HTTP к внешним моделям: таймауты, retry с backoff, graceful-деградация (NFR-REL-03)."""
from __future__ import annotations

import asyncio
import logging
import random

import httpx

from app.adapters.vision.base import ProviderUnavailable
from app.core.config import settings

logger = logging.getLogger(__name__)

# Что имеет смысл повторять: сеть моргнула, лимит запросов, временная ошибка на той стороне.
_RETRIABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


async def post_json(url: str, *, json: dict, headers: dict | None = None,
                    provider: str = "external") -> dict:
    """POST с повторными попытками. Исчерпали попытки -> ProviderUnavailable.

    4xx (кроме перечисленных) не повторяем: неверный ключ или кривой запрос от
    повтора не починятся, а деньги и время потратятся.
    """
    attempts = max(1, settings.external_max_attempts)
    timeout = httpx.Timeout(settings.external_timeout_seconds)
    last_error: str = ""

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(url, json=json, headers=headers or {})
                if response.status_code < 400:
                    return response.json()

                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code not in _RETRIABLE_STATUS:
                    logger.warning("%s: неповторяемая ошибка %s", provider, last_error)
                    raise ProviderUnavailable(f"{provider}: {last_error}")
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            except ProviderUnavailable:
                raise
            except ValueError as exc:                      # тело не является JSON
                last_error = f"некорректный ответ: {exc}"

            if attempt < attempts:
                # экспоненциальный backoff + джиттер, чтобы попытки не били залпом
                delay = settings.external_backoff_seconds * (2 ** (attempt - 1))
                delay += random.uniform(0, settings.external_backoff_seconds / 2)
                logger.info("%s: попытка %d/%d не удалась (%s), пауза %.1f с",
                            provider, attempt, attempts, last_error, delay)
                await asyncio.sleep(delay)

    raise ProviderUnavailable(f"{provider}: исчерпаны попытки ({attempts}). {last_error}")
