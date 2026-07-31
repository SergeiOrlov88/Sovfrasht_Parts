# -*- coding: utf-8 -*-
"""Аутентификация (docs/08 §2, FR-AUTH-01)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.org import User
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserRead,
)
from app.services import auth_service

router = APIRouter(tags=["auth"])


@router.post("/auth/token", response_model=TokenResponse, summary="Вход по логину и паролю")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await auth_service.authenticate(db, payload.login, payload.password)
    access, refresh, expires_in = auth_service.issue_tokens(user)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/auth/refresh", response_model=AccessTokenResponse, summary="Обновление access-токена")
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    access, expires_in = await auth_service.refresh_access_token(db, payload.refresh_token)
    return AccessTokenResponse(access_token=access, expires_in=expires_in)


@router.get("/auth/me", response_model=UserRead, summary="Текущий пользователь и роль")
async def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)
