# -*- coding: utf-8 -*-
"""Перечисления домена. В БД хранятся строками с CHECK-ограничением:
native enum в Postgres тяжело менять миграциями, а набор значений будет расти.
"""
import enum


class Role(str, enum.Enum):
    """Роли RBAC (FR-AUTH-02, NFR-SEC-03)."""
    mechanic = "mechanic"                    # механик
    supplier_manager = "supplier_manager"    # снабженец
    fleet_owner = "fleet_owner"              # судовладелец / суперинтендант
    expert = "expert"                        # оператор HITL
    admin = "admin"                          # администратор


class OrganizationType(str, enum.Enum):
    owner = "owner"        # владелец флота
    shipyard = "shipyard"  # верфь


class ScanStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    done = "done"
    needs_review = "needs_review"
    error = "error"


class PhotoKind(str, enum.Enum):
    overview = "overview"      # общий вид
    nameplate = "nameplate"    # шильдик
    context = "context"        # место установки


class RecognitionStatus(str, enum.Enum):
    auto = "auto"
    confirmed = "confirmed"
    corrected = "corrected"
    rejected = "rejected"


class CompatibilityType(str, enum.Enum):
    full = "full"
    partial = "partial"
    kit = "kit"


class SupplierType(str, enum.Enum):
    marketplace = "marketplace"   # площадка (ShipServ и т.п.)
    supplier = "supplier"         # дистрибьютор
    oem = "oem"                   # производитель
    reman = "reman"               # восстановление/ремануфактуринг


class OfferSource(str, enum.Enum):
    """Откуда получено предложение. Пока всё curated; ADR-05 в docs/06 описывает,
    как рядом встанет api-провайдер конкретного производителя."""
    curated = "curated"           # курируемый список, заведён вручную
    demo = "demo"                 # демонстрационные данные пилота
    api = "api"                   # получено из внешнего API поставщика


class StockStatus(str, enum.Enum):
    in_stock = "in"
    low = "low"
    out = "out"


class RepairVerdict(str, enum.Enum):
    repair = "repair"
    replace = "replace"


class RequestPriority(str, enum.Enum):
    low = "low"
    normal = "normal"
    urgent = "urgent"


class RequestStatus(str, enum.Enum):
    new = "new"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    ordered = "ordered"
    received = "received"


class ModerationStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    resolved = "resolved"


class ModerationResolution(str, enum.Enum):
    confirmed = "confirmed"
    corrected = "corrected"
    rejected = "rejected"


class TrainingSampleSource(str, enum.Enum):
    user_feedback = "user_feedback"
    expert = "expert"


def values(e: type[enum.Enum]) -> list[str]:
    """Значения перечисления — для CHECK-ограничений в моделях."""
    return [m.value for m in e]
