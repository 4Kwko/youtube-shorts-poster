"""Endpoint de health check."""

from __future__ import annotations

from anyio import to_thread
from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.schemas.health import HealthResponse
from app.services.health import build_health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health(settings: SettingsDep) -> HealthResponse:
    # A detecção de binários pode disparar subprocessos quando o cache expira.
    # Rodar na threadpool evita bloquear o event loop.
    return await to_thread.run_sync(build_health, settings)
