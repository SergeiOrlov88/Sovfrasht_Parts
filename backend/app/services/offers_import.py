# -*- coding: utf-8 -*-
"""Загрузчик демо-предложений поставщиков (C1).

Формат `seed/offers_seed.csv`:
    part_oem, supplier_name, supplier_type, supplier_region, supplier_url,
    price, lead_time, stock_status, deep_link

Привязка к детали — по `part_oem` (OEM-номер позиции каталога), поэтому каталог
должен быть залит первым. Все записи помечаются source=demo: цены и сроки
демонстрационные, и их надо отличать от полученных по API (ADR-05).

Запуск:
    python -m app.offers_import                       # seed/offers_seed.csv
    python -m app.offers_import path.csv --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.vision.nameplate import normalize_code
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.catalog import Part, Supplier, SupplierOffer
from app.services.catalog_import import read_rows

# В файле типы поставщиков записаны по-русски — приводим к значениям перечисления
SUPPLIER_TYPE_MAP = {
    "площадка": "marketplace",
    "маркетплейс": "marketplace",
    "дистрибьютор": "supplier",
    "поставщик": "supplier",
    "oem": "oem",
    "производитель": "oem",
    "восстановление": "reman",
    "реман": "reman",
}

STOCK_VALUES = {"in", "low", "out"}


@dataclass
class OffersReport:
    suppliers_created: int = 0
    offers_created: int = 0
    offers_updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Поставщиков добавлено: {self.suppliers_created}",
            f"Предложений добавлено: {self.offers_created}",
            f"Предложений обновлено: {self.offers_updated}",
            f"Пропущено:             {self.skipped}",
        ]
        if self.warnings:
            lines.append(f"\nПредупреждения ({len(self.warnings)}):")
            lines += [f"  ! {w}" for w in self.warnings[:20]]
        if self.errors:
            lines.append(f"\nОшибки ({len(self.errors)}):")
            lines += [f"  x {e}" for e in self.errors[:20]]
        return "\n".join(lines)


async def _get_or_create_supplier(db: AsyncSession, name: str, type_raw: str,
                                  region: str | None, url: str | None,
                                  report: OffersReport) -> Supplier:
    supplier = await db.scalar(select(Supplier).where(Supplier.name == name))
    stype = SUPPLIER_TYPE_MAP.get((type_raw or "").strip().lower())
    if stype is None:
        stype = "supplier"
        if type_raw:
            report.warnings.append(f"неизвестный тип поставщика «{type_raw}» -> supplier")

    if supplier is None:
        supplier = Supplier(name=name, type=stype, region=region or None, url=url or None)
        db.add(supplier)
        await db.flush()
        report.suppliers_created += 1
    else:
        supplier.type = stype
        supplier.region = region or supplier.region
        supplier.url = url or supplier.url
    return supplier


async def import_offers(db: AsyncSession, rows: list[dict], *, dry_run: bool = False,
                        source: str | None = None) -> OffersReport:
    report = OffersReport()
    source = source or settings.offers_default_source
    now = datetime.now(timezone.utc)

    for index, raw in enumerate(rows, start=2):
        row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
        part_oem = normalize_code(row.get("part_oem"))
        supplier_name = (row.get("supplier_name") or "").strip()

        if not part_oem or not supplier_name:
            report.errors.append(f"строка {index}: нужны part_oem и supplier_name")
            report.skipped += 1
            continue

        part = await db.scalar(select(Part).where(Part.oem_number_norm == part_oem))
        if part is None:
            # Каталог заливается первым — иначе привязывать не к чему
            report.errors.append(
                f"строка {index}: деталь с OEM «{row.get('part_oem')}» не найдена в каталоге"
            )
            report.skipped += 1
            continue

        stock = (row.get("stock_status") or "").strip().lower() or None
        if stock and stock not in STOCK_VALUES:
            report.warnings.append(f"строка {index}: наличие «{stock}» не распознано, поле пусто")
            stock = None

        supplier = await _get_or_create_supplier(
            db, supplier_name, row.get("supplier_type"), row.get("supplier_region"),
            row.get("supplier_url"), report)

        offer = await db.scalar(select(SupplierOffer).where(
            SupplierOffer.part_id == part.id, SupplierOffer.supplier_id == supplier.id))
        is_new = offer is None
        if is_new:
            offer = SupplierOffer(part_id=part.id, supplier_id=supplier.id)
            db.add(offer)

        offer.price = (row.get("price") or "").strip() or None
        offer.lead_time = (row.get("lead_time") or "").strip() or None
        offer.stock_status = stock
        offer.deep_link = (row.get("deep_link") or "").strip() or None
        offer.source = source
        offer.fetched_at = now

        report.offers_created += int(is_new)
        report.offers_updated += int(not is_new)

    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return report


async def main_async(path: Path, dry_run: bool) -> int:
    rows = read_rows(path)
    print(f"Прочитано строк: {len(rows)}")
    async with SessionLocal() as db:
        report = await import_offers(db, rows, dry_run=dry_run)
    print(("— ПРОВЕРКА (dry-run), в базу ничего не записано —\n" if dry_run else "")
          + report.render())
    return 1 if report.errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт предложений поставщиков (CSV/JSON)")
    parser.add_argument("path", type=Path, nargs="?", default=Path("seed/offers_seed.csv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.path.exists():
        print(f"Файл не найден: {args.path}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main_async(args.path, args.dry_run)))


if __name__ == "__main__":
    main()
