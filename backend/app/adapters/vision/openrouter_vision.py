# -*- coding: utf-8 -*-
"""Опознание судовой детали фронтир-моделью зрения через OpenRouter.

Зачем понадобился отдельный провайдер (спайк по итогам демо):
каталог MVP — 57 позиций, и реальная деталь в него, как правило, не попадает.
Прежний путь (Yandex OCR → матч по каталогу) в таком случае отвечал «не найдено»
и молчал по существу. Здесь модель отвечает на главный вопрос «что это за
деталь» сама, а каталог становится обогащением: нашли номер — добавили коды,
поставщиков и ремонт; не нашли — ответ всё равно содержателен.

Провайдер реализует тот же VisionProvider, что и остальные (docs/06,
«Адаптеры для vision/OCR»), поэтому включается переключателем в .env и не
требует правок конвейера.
"""
from __future__ import annotations

import base64
import logging

from app.adapters.vision.base import PhotoInput, VisionProvider, VisionResult
from app.adapters.vision.http import post_json
from app.adapters.vision.vision_llm import parse_vision_reply
from app.core.config import settings

logger = logging.getLogger(__name__)

# Промпт намеренно требует ответить даже при неполной уверенности: пустой ответ
# бесполезен механику, а честная оговорка в notes — полезна. Плюс явный запрет
# выдумывать номера: галлюцинация артикула хуже, чем его отсутствие.
_PROMPT = (
    "Ты — судовой инженер-эксперт по судовому оборудованию и запчастям. "
    "На фото — деталь или узел с судна. Определи, что это.\n\n"
    "Правила:\n"
    "1. Отвечай по существу даже если не уверен полностью — укажи это в notes "
    "и снизь confidence. Ответ «не знаю» недопустим.\n"
    "2. Номера и маркировку переписывай ТОЛЬКО те, что реально видишь на фото. "
    "Не додумывай и не восстанавливай артикулы по памяти.\n"
    "3. Если на детали виден шильдик — прочитай его полностью.\n"
    "4. function — зачем эта деталь нужна на судне, простыми словами.\n"
    "5. Все текстовые поля заполняй ПО-РУССКИ (интерфейс русский, NFR-L10N-01). "
    "Исключение — markings: маркировку переписывай ровно так, как она написана "
    "на детали, не переводя.\n\n"
    "Ответь СТРОГО одним JSON-объектом, без markdown и пояснений:\n"
    "{"
    '"part_type": "<что это за деталь/узел>", '
    '"maker": "<производитель или null>", '
    '"model": "<модель/серия или null>", '
    '"function": "<назначение на судне, 1-2 предложения>", '
    '"markings": "<все видимые номера и надписи или null>", '
    '"confidence": <целое 0-100>, '
    '"notes": "<что мешает уверенному ответу или null>"'
    "}"
)


def _as_text(value) -> str | None:
    """Модель может вернуть null, число или вложенный список — приводим к строке."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v) for v in value if v)
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "неизвестно"}:
        return None
    return text


class OpenRouterVisionProvider(VisionProvider):
    """OpenAI-совместимый chat/completions OpenRouter с картинками.

    Модель задаётся в .env (OPENROUTER_MODEL), ключ — один на все модели.
    """

    name = "openrouter_vision"

    async def describe(self, photos: list[PhotoInput]) -> VisionResult:
        parts: list[dict] = [{"type": "text", "text": _PROMPT}]
        for photo in photos:
            b64 = base64.b64encode(photo.content).decode("ascii")
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{photo.mime_type};base64,{b64}"},
            })

        payload = {
            "model": settings.openrouter_model,
            "messages": [{"role": "user", "content": parts}],
            "max_tokens": settings.openrouter_max_tokens,
            "temperature": 0,          # нужен воспроизводимый ответ, не творчество
        }
        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        # OpenRouter просит помечать приложение — влияет на лимиты и статистику
        if settings.openrouter_referer:
            headers["HTTP-Referer"] = settings.openrouter_referer
        if settings.openrouter_title:
            headers["X-Title"] = settings.openrouter_title

        data = await post_json(settings.openrouter_url, json=payload,
                               headers=headers, provider=self.name)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("%s: неожиданная форма ответа", self.name)
            content = ""

        parsed = parse_vision_reply(content if isinstance(content, str) else "")

        raw_conf = parsed.get("confidence", 0)
        confidence = int(raw_conf) if isinstance(raw_conf, (int, float)) else 0

        part_type = _as_text(parsed.get("part_type"))
        maker = _as_text(parsed.get("maker"))
        model = _as_text(parsed.get("model"))
        function = _as_text(parsed.get("function"))
        markings = _as_text(parsed.get("markings"))
        notes = _as_text(parsed.get("notes"))

        # description собираем сами: старый код конвейера и отчёт читают именно
        # его, и он должен остаться осмысленным одной строкой.
        description = " ".join(x for x in (
            " ".join(p for p in (maker, model, part_type) if p),
            function,
        ) if x).strip()

        return VisionResult(
            description=description,
            category=part_type,
            maker=maker,
            model_version=f"{self.name}:{settings.openrouter_model}",
            confidence=max(0, min(confidence, 100)),
            raw=parsed,
            part_type=part_type,
            model=model,
            function=function,
            markings=markings,
            notes=notes,
        )
