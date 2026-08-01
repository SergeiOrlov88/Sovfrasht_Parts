# -*- coding: utf-8 -*-
"""Ремонт или замена (D1, FR-REPAIR-01/02).

Правила — отраслевые эвристики по типу детали (`specs.subtype`), а НЕ приговор
по конкретному экземпляру: фактический износ, наличие сервиса в порту и стоимость
простоя правило не знает. Поэтому рекомендация всегда сопровождается
дисклеймером (FR-REPAIR-02), и решение остаётся за механиком.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Part, RepairInfo
from app.models.enums import RepairVerdict
from app.services.catalog_import import read_rows

DISCLAIMER = (
    "Рекомендация носит справочный характер: она построена на отраслевом правиле "
    "для этого типа детали и не учитывает фактический износ конкретного экземпляра. "
    "Финальное решение принимает механик с учётом состояния детали, наличия "
    "сервиса в порту и стоимости простоя судна."
)

# Диапазон вида «50–60%» / «30-50 %» — берём обе границы
_SHARE = re.compile(r"(\d+)\s*[–\-—]\s*(\d+)\s*%?|(\d+)\s*%")
# Из строки цены достаём число: «$1 190» -> 1190
_PRICE = re.compile(r"\d[\d\s  ]*")


@dataclass
class RepairRule:
    subtype: str
    category: str | None
    default_verdict: str
    rationale: str | None
    typical_repair_share: str | None
    typical_repair_time: str | None


@dataclass
class RulesReport:
    rules_loaded: int = 0
    parts_matched: int = 0
    parts_unknown: int = 0
    created: int = 0
    updated: int = 0
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Правил загружено:       {self.rules_loaded}",
            f"Позиций с правилом:     {self.parts_matched}",
            f"Позиций без правила:    {self.parts_unknown} (verdict=unknown)",
            f"RepairInfo добавлено:   {self.created}",
            f"RepairInfo обновлено:   {self.updated}",
        ]
        if self.warnings:
            lines.append(f"\nПредупреждения ({len(self.warnings)}):")
            lines += [f"  ! {w}" for w in self.warnings[:20]]
        return "\n".join(lines)


def parse_share(share: str | None) -> tuple[int, int] | None:
    """«50–60%» -> (50, 60); «40%» -> (40, 40); «—» -> None."""
    if not share:
        return None
    match = _SHARE.search(share)
    if not match:
        return None
    if match.group(1) and match.group(2):
        low, high = int(match.group(1)), int(match.group(2))
        return (min(low, high), max(low, high))
    if match.group(3):
        value = int(match.group(3))
        return (value, value)
    return None


def parse_price(price: str | None) -> float | None:
    """Достаёт число из строковой цены. Точность приблизительная — см. техдолг
    в docs/08: при подключении API цена станет числовой с валютой."""
    if not price:
        return None
    match = _PRICE.search(price)
    if not match:
        return None
    digits = "".join(ch for ch in match.group(0) if ch.isdigit())
    return float(digits) if digits else None


def estimate_repair_cost(replace_price: str | None, share: str | None) -> str | None:
    """Ориентировочная стоимость ремонта = доля от цены замены.

    Валюту берём из исходной строки как есть — арифметика между валютами
    невозможна, и смешивать источники мы не пытаемся.
    """
    amount = parse_price(replace_price)
    bounds = parse_share(share)
    if amount is None or bounds is None:
        return None
    low, high = bounds
    currency = (replace_price or "").strip()[:1]
    currency = currency if not currency.isdigit() else ""
    lo, hi = round(amount * low / 100), round(amount * high / 100)
    fmt = lambda v: f"{currency}{v:,.0f}".replace(",", " ")   # noqa: E731
    return fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"


# ── Загрузка правил ──────────────────────────────────────────────────────────

def load_rules(path: Path) -> dict[str, RepairRule]:
    rules: dict[str, RepairRule] = {}
    for row in read_rows(path):
        subtype = (row.get("subtype") or "").strip()
        if not subtype:
            continue
        share = (row.get("typical_repair_share") or "").strip()
        time = (row.get("typical_repair_time") or "").strip()
        rules[subtype] = RepairRule(
            subtype=subtype,
            category=(row.get("category") or "").strip() or None,
            default_verdict=(row.get("default_verdict") or "").strip().lower() or "unknown",
            rationale=(row.get("rationale") or "").strip() or None,
            # «—» в файле означает «неприменимо», а не значение
            typical_repair_share=share if share and share not in {"—", "-"} else None,
            typical_repair_time=time if time and time not in {"—", "-"} else None,
        )
    return rules


async def apply_rules(db: AsyncSession, rules: dict[str, RepairRule],
                      dry_run: bool = False) -> RulesReport:
    """Наполняет RepairInfo для позиций каталога по их specs.subtype."""
    report = RulesReport(rules_loaded=len(rules))
    parts = list((await db.scalars(select(Part))).all())

    for part in parts:
        subtype = (part.specs or {}).get("subtype")
        rule = rules.get(subtype) if subtype else None

        info = await db.scalar(select(RepairInfo).where(RepairInfo.part_id == part.id))
        is_new = info is None
        if is_new:
            info = RepairInfo(part_id=part.id, verdict=RepairVerdict.unknown.value)
            db.add(info)

        if rule is None:
            # Правила нет — честный unknown, а не догадка
            info.verdict = RepairVerdict.unknown.value
            info.rationale = ("Для этого типа детали отраслевого правила пока нет — "
                              "оцените ремонтопригодность на месте.")
            info.repair_share = None
            info.repair_time = None
            info.rule_subtype = subtype
            report.parts_unknown += 1
            if subtype:
                report.warnings.append(f"нет правила для subtype «{subtype}» ({part.name})")
        else:
            info.verdict = rule.default_verdict
            info.rationale = rule.rationale
            info.repair_share = rule.typical_repair_share
            info.repair_time = rule.typical_repair_time
            info.rule_subtype = rule.subtype
            report.parts_matched += 1

        report.created += int(is_new)
        report.updated += int(not is_new)

    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return report


async def get_repair_info(db: AsyncSession, part_id: uuid.UUID) -> RepairInfo | None:
    return await db.scalar(select(RepairInfo).where(RepairInfo.part_id == part_id))
