# -*- coding: utf-8 -*-
"""Спайк: прогон vision-провайдера по реальным фото, без БД и очереди.

Зачем отдельный скрипт: на демо вскрылось, что деталей вне каталога из 57 позиций
приложение не опознаёт. Прежде чем менять прод-путь, надо увидеть, что модель
вообще отвечает по существу на настоящих фотографиях.

Запуск (ключ из .env, в терминал не печатается):
    cd backend
    python spike_openrouter.py ../photos/graviner_mk5.jpg ../photos/sperry_5016.jpg

Можно указать несколько фото одной детали — они уйдут в модель одним запросом.
Модель берётся из OPENROUTER_MODEL, переопределяется флагом --model.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

# Скрипт лежит в backend/scripts/, а пакет app — в backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.adapters.vision.base import PhotoInput  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import storage  # noqa: E402


def load_photo(path: Path, kind: str) -> PhotoInput:
    content = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return PhotoInput(content=content, mime_type=mime, kind=kind,
                      sha256=storage.sha256_of(content))


async def main() -> int:
    ap = argparse.ArgumentParser(description="Спайк опознания детали через OpenRouter")
    ap.add_argument("photos", nargs="+", type=Path, help="файлы фотографий")
    ap.add_argument("--model", help="переопределить OPENROUTER_MODEL")
    ap.add_argument("--separate", action="store_true",
                    help="прогнать каждое фото отдельным запросом, а не одним")
    args = ap.parse_args()

    missing = [p for p in args.photos if not p.exists()]
    if missing:
        print("Не найдены файлы: " + ", ".join(str(p) for p in missing))
        return 2

    if args.model:
        settings.openrouter_model = args.model
    if not settings.openrouter_api_key:
        print("OPENROUTER_API_KEY пуст. Задайте его в backend/.env — в терминал не выводится.")
        return 2

    # Импорт после проверки ключа: провайдер читает настройки при вызове
    from app.adapters.vision.openrouter_vision import OpenRouterVisionProvider

    provider = OpenRouterVisionProvider()
    print(f"модель: {settings.openrouter_model}")
    print(f"фото:   {len(args.photos)} шт., режим: "
          f"{'по одному' if args.separate else 'все вместе одним запросом'}")
    print()

    groups = ([[p] for p in args.photos] if args.separate else [list(args.photos)])

    for group in groups:
        inputs = [load_photo(p, "nameplate" if i == 0 else "overview")
                  for i, p in enumerate(group)]
        names = ", ".join(p.name for p in group)
        print("=" * 78)
        print(f"ФОТО: {names}")
        print("=" * 78)

        t0 = time.monotonic()
        try:
            result = await provider.describe(inputs)
        except Exception as exc:                       # noqa: BLE001 — спайк, показываем как есть
            print(f"  ОШИБКА: {type(exc).__name__}: {exc}")
            continue
        elapsed = time.monotonic() - t0

        print(f"  тип детали:     {result.part_type or '—'}")
        print(f"  производитель:  {result.maker or '—'}")
        print(f"  модель/серия:   {result.model or '—'}")
        print(f"  назначение:     {result.function or '—'}")
        print(f"  маркировка:     {result.markings or '—'}")
        print(f"  уверенность:    {result.confidence}")
        print(f"  оговорки:       {result.notes or '—'}")
        print()
        print(f"  заголовок для отчёта: {result.title or '—'}")
        print(f"  время ответа: {elapsed:.1f} с | {result.model_version}")
        print()
        print("  сырой JSON модели:")
        print("    " + json.dumps(result.raw, ensure_ascii=False, indent=2).replace("\n", "\n    "))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
