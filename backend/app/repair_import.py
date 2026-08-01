# -*- coding: utf-8 -*-
"""Загрузка правил ремонтопригодности и наполнение RepairInfo (D1).

Правила — отраслевые эвристики по типу детали (specs.subtype). Каталог должен
быть залит первым: правила применяются к уже существующим позициям.

Запуск:
    python -m app.repair_import                          # seed/repair_rules_seed.csv
    python -m app.repair_import path.csv --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.services import repair_service


async def main_async(path: Path, dry_run: bool) -> int:
    rules = repair_service.load_rules(path)
    print(f"Правил прочитано: {len(rules)}")
    async with SessionLocal() as db:
        report = await repair_service.apply_rules(db, rules, dry_run=dry_run)
    print(("— ПРОВЕРКА (dry-run), в базу ничего не записано —\n" if dry_run else "")
          + report.render())
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт правил ремонтопригодности")
    parser.add_argument("path", type=Path, nargs="?",
                        default=Path("seed/repair_rules_seed.csv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.path.exists():
        print(f"Файл не найден: {args.path}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main_async(args.path, args.dry_run)))


if __name__ == "__main__":
    main()
