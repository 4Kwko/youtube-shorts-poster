"""Regras do health check, isoladas da camada HTTP."""

from __future__ import annotations

import time

from app.core.config import Settings
from app.schemas.health import DependencyStatus, HealthResponse
from app.services.media.binaries import MediaBinary, get_binary_status

_STARTED_AT = time.monotonic()


def uptime_seconds() -> float:
    return time.monotonic() - _STARTED_AT


def check_dependencies() -> DependencyStatus:
    """Disponibilidade das dependências externas.

    Nunca levanta: a indisponibilidade de um binário é informação do health
    check, não uma falha dele.
    """
    return DependencyStatus(
        ffmpeg=get_binary_status(MediaBinary.FFMPEG).available,
        ffprobe=get_binary_status(MediaBinary.FFPROBE).available,
    )


def build_health(settings: Settings) -> HealthResponse:
    return HealthResponse(
        status="ok",
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        uptime_seconds=round(uptime_seconds(), 3),
        dependencies=check_dependencies(),
    )
