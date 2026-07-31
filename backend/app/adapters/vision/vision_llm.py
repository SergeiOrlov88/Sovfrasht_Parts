# -*- coding: utf-8 -*-
"""Fallback: облачная vision-модель — когда шильдик не читается (docs/06).

Определяет ТИП детали по фото. Результат заведомо менее надёжен, чем номер с
шильдика, поэтому confidence сверху ограничен vision_fallback_max_confidence —
такой скан уходит эксперту (FR-REC-04, NFR-ACC-03).
"""
from __future__ import annotations

import base64
import json
import logging

from app.adapters.vision.base import PhotoInput, VisionProvider, VisionResult
from app.adapters.vision.http import post_json
from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT = (
    "Ты — судовой механик-эксперт. На фото судовая деталь. Определи, что это. "
    "Ответь СТРОГО одним JSON-объектом без пояснений и без markdown:\n"
    '{"category": "<категория, напр. топливная аппаратура/насос>", '
    '"description": "<что за деталь, 1-2 предложения>", '
    '"maker": "<производитель или null>", '
    '"confidence": <целое 0-100, насколько уверен>}'
)


def parse_vision_reply(content: str) -> dict:
    """Достаёт JSON из ответа модели. Модели любят обрамлять его ```json."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        parsed = json.loads(text[start:end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


class VisionLlmProvider(VisionProvider):
    """OpenAI-совместимый chat/completions с картинками (Yandex ART, GPT-4o, Claude)."""

    name = "vision_llm"

    async def describe(self, photos: list[PhotoInput]) -> VisionResult:
        parts: list[dict] = [{"type": "text", "text": _PROMPT}]
        for photo in photos:
            b64 = base64.b64encode(photo.content).decode("ascii")
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{photo.mime_type};base64,{b64}"},
            })

        payload = {
            "model": settings.vision_llm_model,
            "messages": [{"role": "user", "content": parts}],
            "max_tokens": 400,
            "temperature": 0,          # нужен воспроизводимый ответ, не творчество
        }
        headers = {"Authorization": f"Bearer {settings.vision_llm_api_key}"}
        data = await post_json(settings.vision_llm_url, json=payload,
                               headers=headers, provider=self.name)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("%s: неожиданная форма ответа", self.name)
            content = ""

        parsed = parse_vision_reply(content if isinstance(content, str) else "")
        raw_conf = parsed.get("confidence", 0)
        confidence = int(raw_conf) if isinstance(raw_conf, (int, float)) else 0

        return VisionResult(
            description=str(parsed.get("description") or "").strip(),
            category=(str(parsed["category"]).strip() if parsed.get("category") else None),
            maker=(str(parsed["maker"]).strip() if parsed.get("maker") else None),
            model_version=f"{self.name}:{settings.vision_llm_model}",
            # потолок: визуальное опознание не может считаться надёжнее номера
            confidence=max(0, min(confidence, settings.vision_fallback_max_confidence)),
            raw=parsed,
        )
