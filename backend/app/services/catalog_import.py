# -*- coding: utf-8 -*-
"""Загрузчик стартового каталога (FR-CAT-01).

Формат — CSV или JSON с одинаковым набором полей:

    name;category;maker;impa_code;issa_code;oem_number;equipment;specs;aliases;alt_oem

Обязательны `name` и хотя бы один из кодов (`impa_code`/`issa_code`/`oem_number`) —
это же требует CHECK в БД. `specs` — JSON-строка, `aliases` и `alt_oem` — списки
через `;`.

Загрузка идемпотентна: повторный запуск обновляет позиции, а не плодит дубли.
Связи аналогов разрешаются вторым проходом — на момент чтения строки аналог
может быть ещё не загружен.

Запуск:
    python -m app.catalog_import catalog/parts.csv            # залить
    python -m app.catalog_import catalog/parts.csv --dry-run  # только проверить
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.vision.nameplate import normalize_code
from app.core.database import SessionLocal
from app.models.catalog import Part, PartAlias, PartAlternative

FIELDS = ("name", "category", "maker", "impa_code", "issa_code",
          "oem_number", "equipment", "specs", "aliases", "alt_oem")

# Категории MVP: топливная аппаратура и насосы. Незнакомая категория не блокирует
# загрузку, но попадает в предупреждения — чтобы опечатки не расползались молча.
# Написание сверено со стартовым каталогом аналитиков (seed/catalog_seed.csv):
# там используется единственное число «pump». Множественное принимаем тоже,
# чтобы разночтение не блокировало загрузку.
KNOWN_CATEGORIES = {"fuel_equipment", "pump", "pumps"}


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    aliases: int = 0
    alternatives: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Добавлено:   {self.created}",
            f"Обновлено:   {self.updated}",
            f"Пропущено:   {self.skipped}",
            f"Алиасов:     {self.aliases}",
            f"Аналогов:    {self.alternatives}",
        ]
        if self.warnings:
            lines.append(f"\nПредупреждения ({len(self.warnings)}):")
            lines += [f"  ! {w}" for w in self.warnings[:20]]
        if self.errors:
            lines.append(f"\nОшибки ({len(self.errors)}):")
            lines += [f"  x {e}" for e in self.errors[:20]]
        return "\n".join(lines)


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def _parse_specs(value, row_no: int, report: ImportReport) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        report.warnings.append(f"строка {row_no}: specs не разобран как JSON, поле пропущено")
        return None


def read_rows(path: Path) -> list[dict]:
    """CSV или JSON — набор полей одинаковый."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return data if isinstance(data, list) else data.get("parts", [])
    # Разделитель определяем сами: аналитики выгружают и с ';', и с ','
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def _clean(row: dict) -> dict:
    return {k: (v.strip() if isinstance(v, str) else v)
            for k, v in row.items() if k in FIELDS}


async def _find_existing(db: AsyncSession, row: dict) -> Part | None:
    """Ключ идемпотентности: IMPA, иначе (maker, oem)."""
    impa = normalize_code(row.get("impa_code"))
    if impa:
        found = await db.scalar(select(Part).where(Part.impa_code_norm == impa))
        if found:
            return found
    maker = normalize_code(row.get("maker"))
    oem = normalize_code(row.get("oem_number"))
    if oem:
        stmt = select(Part).where(Part.oem_number_norm == oem)
        if maker:
            stmt = stmt.where(Part.maker_norm == maker)
        return await db.scalar(stmt)
    # Кодов нет — ключом идемпотентности становится пара «производитель + название»
    name = (row.get("name") or "").strip()
    if name and maker:
        return await db.scalar(
            select(Part).where(Part.maker_norm == maker, Part.name == name)
        )
    return None


async def import_rows(db: AsyncSession, rows: list[dict], dry_run: bool = False) -> ImportReport:
    report = ImportReport()
    # oem_norm -> Part, чтобы вторым проходом разрешить alt_oem
    by_oem: dict[str, Part] = {}
    pending_alternatives: list[tuple[Part, list[str]]] = []

    for index, raw in enumerate(rows, start=2):        # строка 1 — заголовок
        row = _clean(raw)
        name = (row.get("name") or "").strip()
        codes = [normalize_code(row.get(c)) for c in ("impa_code", "issa_code", "oem_number")]

        if not name:
            report.errors.append(f"строка {index}: пустое поле name")
            report.skipped += 1
            continue
        # Позиция без кодов — норма: у ряда судовых дизелей номера непубличны,
        # опознание идёт по name/maker/equipment. Но совсем неопознаваемую строку
        # (без производителя И без оборудования) не принимаем — инвариант БД.
        maker_raw = (row.get("maker") or "").strip()
        equipment_raw = (row.get("equipment") or "").strip()
        if not maker_raw and not equipment_raw:
            report.errors.append(
                f"строка {index} ({name}): нужен производитель или применимое оборудование — "
                f"иначе позицию нечем опознать"
            )
            report.skipped += 1
            continue
        if not any(codes) and not maker_raw:
            report.warnings.append(
                f"строка {index} ({name}): кодов нет, производитель не указан — "
                f"сопоставление пойдёт только по оборудованию"
            )
        category = (row.get("category") or "").strip() or None
        if category and category not in KNOWN_CATEGORIES:
            report.warnings.append(f"строка {index}: незнакомая категория «{category}»")

        part = await _find_existing(db, row)
        is_new = part is None
        if is_new:
            part = Part(name=name)
            db.add(part)

        part.name = name
        part.category = category
        part.maker = (row.get("maker") or "").strip() or None
        part.impa_code = (row.get("impa_code") or "").strip() or None
        part.issa_code = (row.get("issa_code") or "").strip() or None
        part.oem_number = (row.get("oem_number") or "").strip() or None
        part.equipment = (row.get("equipment") or "").strip() or None
        part.specs = _parse_specs(row.get("specs"), index, report)
        part.impa_code_norm = codes[0] or None
        part.issa_code_norm = codes[1] or None
        part.oem_number_norm = codes[2] or None
        part.maker_norm = normalize_code(part.maker) or None

        await db.flush()
        if part.oem_number_norm:
            by_oem[part.oem_number_norm] = part

        # Алиасы: добавляем недостающие, существующие не трогаем.
        # Читаем запросом, а не через part.aliases: у только что созданного
        # объекта обращение к lazy-связи в async-контексте роняет сессию.
        existing_aliases = set((await db.scalars(
            select(PartAlias.alias_norm).where(PartAlias.part_id == part.id)
        )).all())
        for alias in _split_list(row.get("aliases")):
            alias_norm = normalize_code(alias)
            if alias_norm and alias_norm not in existing_aliases:
                db.add(PartAlias(part_id=part.id, alias=alias, alias_norm=alias_norm))
                existing_aliases.add(alias_norm)
                report.aliases += 1

        alt_list = _split_list(row.get("alt_oem"))
        if alt_list:
            pending_alternatives.append((part, alt_list))

        report.created += int(is_new)
        report.updated += int(not is_new)

    # Второй проход: аналоги — к этому моменту все позиции уже в базе
    for part, alt_codes in pending_alternatives:
        for alt_code in alt_codes:
            alt_norm = normalize_code(alt_code)
            alt = by_oem.get(alt_norm) or await db.scalar(
                select(Part).where(Part.oem_number_norm == alt_norm)
            )
            if alt is None:
                report.warnings.append(
                    f"{part.name}: аналог «{alt_code}» не найден в каталоге — связь не создана"
                )
                continue
            if alt.id == part.id:
                continue
            exists = await db.scalar(select(PartAlternative).where(
                PartAlternative.part_id == part.id, PartAlternative.alt_part_id == alt.id
            ))
            if exists is None:
                db.add(PartAlternative(part_id=part.id, alt_part_id=alt.id, compatibility="full"))
                report.alternatives += 1

    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return report


async def main_async(path: Path, dry_run: bool) -> int:
    rows = read_rows(path)
    print(f"Прочитано строк: {len(rows)}")
    async with SessionLocal() as db:
        report = await import_rows(db, rows, dry_run=dry_run)
    print(("— ПРОВЕРКА (dry-run), в базу ничего не записано —\n" if dry_run else "") + report.render())
    return 1 if report.errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт каталога деталей (CSV/JSON)")
    parser.add_argument("path", type=Path, nargs="?",
                        default=Path("seed/catalog_seed.csv"),
                        help="CSV или JSON с каталогом (по умолчанию seed/catalog_seed.csv)")
    parser.add_argument("--dry-run", action="store_true", help="только проверить файл")
    args = parser.parse_args()
    if not args.path.exists():
        print(f"Файл не найден: {args.path}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main_async(args.path, args.dry_run)))


if __name__ == "__main__":
    main()
