"""Erros da camada de renderização."""

from __future__ import annotations

from app.core.errors import AppError


class RenderError(AppError):
    status_code = 500
    code = "render_error"


class RenderSourceUnavailableError(RenderError):
    """Falta o arquivo do clip de origem."""

    status_code = 422
    code = "render_source_unavailable"


class RenderFailedError(RenderError):
    """O FFmpeg não produziu um render utilizável."""

    status_code = 500
    code = "render_failed"
