# -*- coding: utf-8 -*-
"""Конвейер распознавания (A2, FR-REC-01..05).

Порядок ветвления задан docs/06 и FR-REC-02: сначала OCR шильдика — номер детали
приоритетнее визуальной категоризации. Если шильдик не читается, идём в
vision-модель с заведомо более низким confidence, и такой результат уходит
эксперту (FR-REC-04, NFR-ACC-03).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.vision.base import OcrResult, PhotoInput, ProviderUnavailable, VisionResult
from app.adapters.vision.registry import get_ocr_provider, get_vision_provider
from app.core.config import settings
from app.models.enums import ModerationStatus, PhotoKind, RecognitionStatus, ScanStatus
from app.models.scan import (
    ModerationTask, Photo, Recognition, RecognitionCandidate, Scan,
)
from app.models.vision_cache import VisionCache
from app.services import catalog_service, storage
from app.services.catalog_service import CatalogStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineOutcome:
    scan_status: ScanStatus
    confidence: int
    model_version: str
    needs_expert: bool
    used_fallback: bool
    cache_hits: int = 0
    catalog_status: str = CatalogStatus.not_found.value
    candidates_count: int = 0


# ── Кэш платных вызовов (NFR-COST-01) ────────────────────────────────────────
async def _cache_get(db: AsyncSession, provider: str, sha: str) -> dict | None:
    if not settings.vision_cache_enabled:
        return None
    row = await db.scalar(
        select(VisionCache).where(
            VisionCache.provider == provider, VisionCache.image_sha256 == sha
        )
    )
    if row is None:
        return None
    # Просроченную запись считаем промахом: модели обновляются, ответ мог устареть.
    # Postgres отдаёт created_at с таймзоной, SQLite (тесты) — без неё, поэтому
    # naive-значение трактуем как UTC: в БД время и так хранится в UTC (docs/07 §3).
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_limit = datetime.now(timezone.utc) - timedelta(days=settings.vision_cache_ttl_days)
    if created_at < age_limit:
        return None
    row.hit_count += 1
    return row.payload


async def _cache_put(db: AsyncSession, provider: str, sha: str,
                     model_version: str, payload: dict) -> None:
    if not settings.vision_cache_enabled:
        return
    exists = await db.scalar(
        select(VisionCache).where(
            VisionCache.provider == provider, VisionCache.image_sha256 == sha
        )
    )
    if exists is None:
        db.add(VisionCache(provider=provider, image_sha256=sha,
                           model_version=model_version, payload=payload))


# ── Оценка достоверности (FR-REC-03) ─────────────────────────────────────────
def score_ocr(result: OcrResult) -> int:
    """Считаем по тому, что реально извлекли: номер весит больше всего.

    Шкала подобрана так, чтобы «номер + производитель» уверенно проходили порог 70,
    а один только текст без номера — нет.
    """
    score = 0
    if result.oem_number:
        score += 55
    if result.maker:
        score += 15
    if result.serial_number:
        score += 10
    if len(result.text.strip()) >= 20:
        score += 15
    elif result.text.strip():
        score += 5
    return max(0, min(score, 100))


def _pick_photos(photos: list[Photo]) -> tuple[list[Photo], list[Photo]]:
    """Возвращает (для OCR, для vision). Шильдик — приоритетный кадр для OCR."""
    nameplates = [p for p in photos if p.kind == PhotoKind.nameplate.value]
    return (nameplates or list(photos)), list(photos)


async def _load(photo: Photo) -> PhotoInput:
    content = storage.get_object_sync(photo.storage_key)
    return PhotoInput(
        content=content,
        mime_type=photo.mime_type or "image/jpeg",
        kind=photo.kind,
        sha256=photo.content_sha256 or storage.sha256_of(content),
    )


async def run_pipeline(db: AsyncSession, scan_id: uuid.UUID) -> PipelineOutcome:
    """Полный проход по скану. Бросает ProviderUnavailable, если внешние сервисы легли."""
    scan = await db.scalar(
        select(Scan).options(selectinload(Scan.photos)).where(Scan.id == scan_id)
    )
    if scan is None:
        raise ValueError(f"Скан {scan_id} не найден")
    if not scan.photos:
        raise ValueError(f"У скана {scan_id} нет фото")

    scan.status = ScanStatus.processing.value
    await db.commit()

    ocr_photos, all_photos = _pick_photos(scan.photos)
    ocr_provider = get_ocr_provider()
    cache_hits = 0

    # ── Ветка 1: OCR шильдика (приоритет по FR-REC-02) ──────────────────────
    best = OcrResult()
    best_score = -1
    for photo in ocr_photos:
        data = await _load(photo)
        cached = await _cache_get(db, ocr_provider.name, data.sha256)
        if cached is not None:
            cache_hits += 1
            result = OcrResult(**{k: v for k, v in cached.items() if k in OcrResult.__slots__})
        else:
            result = await ocr_provider.recognize_text(data)
            await _cache_put(db, ocr_provider.name, data.sha256, result.model_version, {
                "text": result.text, "maker": result.maker, "oem_number": result.oem_number,
                "serial_number": result.serial_number, "model_version": result.model_version,
                "text_confidence": result.text_confidence,
            })
        score = score_ocr(result)
        if score > best_score:
            best, best_score = result, score

    used_fallback = False
    vision: VisionResult | None = None
    confidence = max(best_score, 0)
    model_version = best.model_version or ocr_provider.name

    # ── Ветка 2: fallback, если шильдик не прочитался ───────────────────────
    if not best.is_readable:
        vision_provider = get_vision_provider()
        inputs = [await _load(p) for p in all_photos]
        combined_sha = storage.sha256_of("".join(sorted(i.sha256 for i in inputs)).encode())
        cached = await _cache_get(db, vision_provider.name, combined_sha)
        if cached is not None:
            cache_hits += 1
            vision = VisionResult(**{k: v for k, v in cached.items()
                                     if k in VisionResult.__slots__})
        else:
            vision = await vision_provider.describe(inputs)
            await _cache_put(db, vision_provider.name, combined_sha, vision.model_version, {
                "description": vision.description, "category": vision.category,
                "maker": vision.maker, "model_version": vision.model_version,
                "confidence": vision.confidence,
            })
        used_fallback = True
        confidence = vision.confidence
        model_version = vision.model_version or vision_provider.name

    # ── Сопоставление с каталогом (A3, FR-CAT-02) ───────────────────────────
    match = await catalog_service.match(
        db,
        oem_number=best.oem_number,
        maker=best.maker or (vision.maker if vision else None),
        name_hint=(vision.description if vision else None) or best.text or None,
        equipment_hint=vision.category if vision else None,
    )
    # Матчинг уточняет доверие: код нашёлся — выше, не нашёлся — ниже
    confidence = catalog_service.adjust_confidence(confidence, match)

    # ── Сохранение результата (FR-REC-03, FR-REC-05) ────────────────────────
    recognition = await db.scalar(select(Recognition).where(Recognition.scan_id == scan.id))
    if recognition is None:
        recognition = Recognition(scan_id=scan.id)
        db.add(recognition)

    recognition.confidence = confidence
    # Если сработал fallback, показываем описание от vision-модели: обрывок
    # нечитаемого OCR пользователю бесполезен. Сырой ответ OCR при этом не
    # теряется — он лежит в vision_cache и в логах конвейера (FR-REC-05).
    if used_fallback and vision and vision.description:
        recognition.ocr_text = vision.description
    else:
        recognition.ocr_text = best.text or None
    recognition.maker_detected = best.maker or (vision.maker if vision else None)
    recognition.oem_detected = best.oem_number
    recognition.model_version = model_version
    recognition.status = RecognitionStatus.auto.value
    recognition.detected_tokens = best.raw.get("tokens") if best.raw else None
    recognition.catalog_status = match.status.value
    recognition.part_id = match.primary.id if match.primary else None

    # Кандидаты (NFR-ACC-02). Искусственно НЕ добираем: нет совпадений —
    # отчёт честно скажет «нет в каталоге» (решение заказчика).
    await db.flush()
    existing_ids = {c.part_id for c in (await db.scalars(
        select(RecognitionCandidate)
        .where(RecognitionCandidate.recognition_id == recognition.id)
    )).all()}
    for candidate in match.candidates:
        if candidate.part.id in existing_ids:
            continue
        db.add(RecognitionCandidate(recognition_id=recognition.id, part_id=candidate.part.id,
                                    relevance=round(candidate.relevance, 4)))
        existing_ids.add(candidate.part.id)

    needs_expert = confidence < settings.confidence_threshold
    scan.status = (ScanStatus.needs_review if needs_expert else ScanStatus.done).value
    await db.flush()

    # Ниже порога — задача эксперту (FR-REC-04, F1). Панель эксперта — шаг 7.
    if needs_expert:
        task_exists = await db.scalar(
            select(ModerationTask).where(ModerationTask.recognition_id == recognition.id)
        )
        if task_exists is None:
            db.add(ModerationTask(recognition_id=recognition.id,
                                  status=ModerationStatus.pending.value))

    await db.commit()
    logger.info("Скан %s: confidence=%d fallback=%s каталог=%s кандидатов=%d "
                "кэш-попаданий=%d -> %s", scan_id, confidence, used_fallback,
                match.status.value, len(match.candidates), cache_hits, scan.status)

    return PipelineOutcome(
        scan_status=ScanStatus(scan.status), confidence=confidence,
        model_version=model_version, needs_expert=needs_expert,
        used_fallback=used_fallback, cache_hits=cache_hits,
        catalog_status=match.status.value, candidates_count=len(match.candidates),
    )


async def mark_error(db: AsyncSession, scan_id: uuid.UUID) -> None:
    """Скан не теряется: остаётся с ошибкой и доступен для переобработки (NFR-REL-02)."""
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
    if scan is not None:
        scan.status = ScanStatus.error.value
        await db.commit()
