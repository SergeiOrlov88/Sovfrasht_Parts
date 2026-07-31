# -*- coding: utf-8 -*-
"""Сопоставление результата распознавания с каталогом (A3, FR-CAT-02/03).

Каскад: точное совпадение по нормализованному коду → алиасы → варианты OCR-
неоднозначностей → префикс → нечёткий pg_trgm. Вектор сознательно не используем:
на узком каталоге точного матча и триграмм достаточно (решение заказчика).

Кандидаты НЕ добираются искусственно: если совпадений нет, отчёт честно говорит
«нет в каталоге», а не подсовывает похожее (решение заказчика).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import func, or_, select  # noqa: F401  (select переиспользуется в тестах)
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.vision.nameplate import code_variants, normalize_code
from app.core.config import settings
from app.models.catalog import Part, PartAlias

logger = logging.getLogger(__name__)


class CatalogStatus(str, Enum):
    matched = "matched"          # точное совпадение по коду
    candidates = "candidates"    # только близкие позиции
    not_found = "not_found"      # в каталоге нет — так и говорим


class MatchMethod(str, Enum):
    impa = "impa"
    issa = "issa"
    oem = "oem"
    alias = "alias"
    ocr_variant = "ocr_variant"  # совпало после исправления O/0, I/1 и т.п.
    prefix = "prefix"
    trigram = "trigram"


# Насколько поднимается/опускается доверие в зависимости от того, как нашли.
# Точный код по IMPA/ISSA — сильнее всего; нечёткий поиск доверие снижает.
_FLOOR = {MatchMethod.impa: 85, MatchMethod.issa: 85, MatchMethod.oem: 80,
          MatchMethod.alias: 78, MatchMethod.ocr_variant: 72}
_FACTOR = {MatchMethod.prefix: 0.9, MatchMethod.trigram: None}   # trigram считается от similarity


@dataclass(slots=True)
class Candidate:
    part: Part
    relevance: float                  # 0..1 — для RecognitionCandidate
    method: MatchMethod


@dataclass(slots=True)
class MatchOutcome:
    status: CatalogStatus
    primary: Part | None = None
    method: MatchMethod | None = None
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def alternatives(self) -> list[Candidate]:
        """Кандидаты без основного — это и есть «альтернативы» из NFR-ACC-02."""
        if self.primary is None:
            return self.candidates
        return [c for c in self.candidates if c.part.id != self.primary.id]


def adjust_confidence(base: int, outcome: MatchOutcome) -> int:
    """Уточняет confidence по итогам матчинга (FR-REC-03).

    Найденный в каталоге код повышает уверенность, ненайденный — понижает.
    Коэффициенты подлежат калибровке на реальных сканах.
    """
    if outcome.status is CatalogStatus.matched and outcome.method in _FLOOR:
        return max(0, min(100, max(base, _FLOOR[outcome.method])))
    if outcome.status is CatalogStatus.candidates:
        top = outcome.candidates[0] if outcome.candidates else None
        if top and top.method is MatchMethod.prefix:
            return int(base * 0.9)
        similarity = top.relevance if top else 0.0
        return int(base * (0.5 + 0.4 * similarity))
    return int(base * 0.5)          # в каталоге не нашли — доверие ниже


async def _exact(db: AsyncSession, column, value: str) -> list[Part]:
    if not value:
        return []
    return list((await db.scalars(select(Part).where(column == value))).all())


async def _by_alias(db: AsyncSession, value: str) -> list[Part]:
    if not value:
        return []
    return list((await db.scalars(
        select(Part).join(PartAlias, PartAlias.part_id == Part.id)
        .where(PartAlias.alias_norm == value)
    )).all())


def _pick_primary(parts: list[Part], maker_norm: str) -> Part:
    """Один номер бывает у разных производителей — разрешаем по maker."""
    if maker_norm:
        for part in parts:
            if part.maker_norm and part.maker_norm == maker_norm:
                return part
    return parts[0]


async def match(db: AsyncSession, *, oem_number: str | None = None, impa_code: str | None = None,
                issa_code: str | None = None, maker: str | None = None,
                name_hint: str | None = None, equipment_hint: str | None = None,
                top_n: int | None = None) -> MatchOutcome:
    """Ищет деталь в каталоге. Возвращает статус, основную позицию и кандидатов."""
    top_n = top_n or settings.catalog_top_n
    oem_norm = normalize_code(oem_number)
    maker_norm = normalize_code(maker)

    # ── Ступень 1: точное совпадение по коду ────────────────────────────────
    for column, value, method in (
        (Part.impa_code_norm, normalize_code(impa_code), MatchMethod.impa),
        (Part.issa_code_norm, normalize_code(issa_code), MatchMethod.issa),
        (Part.oem_number_norm, oem_norm, MatchMethod.oem),
    ):
        found = await _exact(db, column, value)
        if found:
            primary = _pick_primary(found, maker_norm)
            return MatchOutcome(
                status=CatalogStatus.matched, primary=primary, method=method,
                candidates=[Candidate(p, 1.0 if p.id == primary.id else 0.9, method)
                            for p in found[:top_n]],
            )

    # ── Ступень 2: алиасы (те же номера в другом написании) ─────────────────
    found = await _by_alias(db, oem_norm)
    if found:
        primary = _pick_primary(found, maker_norm)
        return MatchOutcome(
            status=CatalogStatus.matched, primary=primary, method=MatchMethod.alias,
            candidates=[Candidate(p, 1.0 if p.id == primary.id else 0.9, MatchMethod.alias)
                        for p in found[:top_n]],
        )

    # ── Ступень 3: варианты OCR-неоднозначностей (O/0, I/1, S/5 …) ──────────
    if oem_norm:
        variants = [v for v in code_variants(oem_norm) if v != oem_norm]
        if variants:
            found = list((await db.scalars(
                select(Part).where(Part.oem_number_norm.in_(variants))
            )).all())
            if not found:
                found = list((await db.scalars(
                    select(Part).join(PartAlias, PartAlias.part_id == Part.id)
                    .where(PartAlias.alias_norm.in_(variants))
                )).all())
            if found:
                primary = _pick_primary(found, maker_norm)
                logger.info("Совпадение по варианту номера: %s -> %s",
                            oem_norm, primary.oem_number_norm)
                return MatchOutcome(
                    status=CatalogStatus.matched, primary=primary,
                    method=MatchMethod.ocr_variant,
                    candidates=[Candidate(p, 0.95, MatchMethod.ocr_variant) for p in found[:top_n]],
                )

    # ── Ступень 4: префикс/вхождение — OCR теряет или добавляет символы ─────
    candidates: list[Candidate] = []
    if oem_norm and len(oem_norm) >= settings.catalog_min_prefix_len:
        rows = list((await db.scalars(
            select(Part).where(or_(
                Part.oem_number_norm.like(f"{oem_norm}%"),
                Part.oem_number_norm.like(f"%{oem_norm}%"),
            )).limit(top_n)
        )).all())
        candidates = [Candidate(p, 0.8, MatchMethod.prefix) for p in rows]

    # ── Ступень 5: нечёткий поиск pg_trgm ───────────────────────────────────
    if not candidates:
        candidates = await _trigram(db, oem_norm, name_hint, top_n)

    # ── Ступень 6: детали без кодов (крупные судовые дизели) ────────────────
    # Часть каталога поставляется без публичных номеров — там опознание идёт
    # по производителю и оборудованию.
    if not candidates and (maker_norm or equipment_hint):
        candidates = await _by_maker_equipment(db, maker_norm, equipment_hint, name_hint, top_n)

    if candidates:
        return MatchOutcome(status=CatalogStatus.candidates, primary=None,
                            candidates=candidates[:top_n])

    # Ничего не нашли — так и сообщаем, «похожее» силой не подбираем
    return MatchOutcome(status=CatalogStatus.not_found)


async def _trigram(db: AsyncSession, oem_norm: str, name_hint: str | None,
                   top_n: int) -> list[Candidate]:
    """Нечёткий поиск. На SQLite (тесты) pg_trgm нет — деградируем до LIKE."""
    dialect = db.bind.dialect.name if db.bind is not None else ""
    threshold = settings.catalog_trigram_threshold

    if dialect != "postgresql":
        needle = (name_hint or oem_norm or "").strip()
        if len(needle) < 3:
            return []
        rows = list((await db.scalars(
            select(Part).where(or_(
                Part.name.ilike(f"%{needle}%"),
                Part.oem_number_norm.ilike(f"%{needle}%"),
            )).limit(top_n)
        )).all())
        return [Candidate(p, 0.5, MatchMethod.trigram) for p in rows]

    results: list[Candidate] = []
    if oem_norm:
        sim = func.similarity(Part.oem_number_norm, oem_norm)
        rows = (await db.execute(
            select(Part, sim.label("s")).where(sim > threshold)
            .order_by(sim.desc()).limit(top_n)
        )).all()
        results += [Candidate(part, float(score), MatchMethod.trigram) for part, score in rows]

    if name_hint and len(results) < top_n:
        sim = func.similarity(Part.name, name_hint)
        rows = (await db.execute(
            select(Part, sim.label("s")).where(sim > threshold)
            .order_by(sim.desc()).limit(top_n)
        )).all()
        seen = {c.part.id for c in results}
        results += [Candidate(part, float(score), MatchMethod.trigram)
                    for part, score in rows if part.id not in seen]

    results.sort(key=lambda c: c.relevance, reverse=True)
    return results[:top_n]


async def _by_maker_equipment(db: AsyncSession, maker_norm: str, equipment_hint: str | None,
                              name_hint: str | None, top_n: int) -> list[Candidate]:
    """Поиск позиций без кодов: по производителю и применимому оборудованию.

    Совпадение здесь заведомо слабее номера, поэтому relevance низкий — такой
    результат почти наверняка уйдёт эксперту.
    """
    if not maker_norm:
        return []
    stmt = select(Part).where(Part.maker_norm == maker_norm)
    hint = (equipment_hint or name_hint or "").strip()
    if hint:
        stmt = stmt.where(or_(Part.equipment.ilike(f"%{hint}%"), Part.name.ilike(f"%{hint}%")))
    rows = list((await db.scalars(stmt.limit(top_n))).all())
    if not rows and hint:
        # Подсказка не совпала — отдаём хотя бы позиции этого производителя
        rows = list((await db.scalars(
            select(Part).where(Part.maker_norm == maker_norm).limit(top_n)
        )).all())
    return [Candidate(p, 0.35, MatchMethod.trigram) for p in rows]
