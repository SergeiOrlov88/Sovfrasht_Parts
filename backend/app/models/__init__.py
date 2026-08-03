# -*- coding: utf-8 -*-
"""Реэкспорт моделей: важно, чтобы Alembic видел все таблицы в Base.metadata."""
from app.models.catalog import (
    Part,
    PartAlias,
    PartAlternative,
    RepairInfo,
    Supplier,
    SupplierOffer,
)
from app.models.org import Organization, User, Vessel, user_vessels
from app.models.scan import (
    ModerationTask,
    PartRequest,
    Photo,
    Recognition,
    RecognitionCandidate,
    Scan,
    TrainingSample,
)
from app.models.notification import Notification
from app.models.vision_cache import VisionCache

__all__ = [
    "Organization", "Vessel", "User", "user_vessels",
    "Scan", "Photo", "Recognition", "RecognitionCandidate",
    "Part", "PartAlias", "PartAlternative", "Supplier", "SupplierOffer", "RepairInfo",
    "PartRequest", "ModerationTask", "TrainingSample", "VisionCache", "Notification",
]
