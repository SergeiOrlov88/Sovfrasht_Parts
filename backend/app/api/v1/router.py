# -*- coding: utf-8 -*-
"""Сборка роутеров версии v1."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth, health, moderation, purchase, scans, users, vessels,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(vessels.router)
api_router.include_router(scans.router)
api_router.include_router(purchase.router)
api_router.include_router(moderation.router)
