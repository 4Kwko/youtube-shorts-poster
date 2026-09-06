"""Erros da camada de clipping."""

from __future__ import annotations

from app.core.errors import AppError


class ClipError(AppError):
    status_code = 500
    code = "clip_error"


class ClipSourceUnavailableError(ClipError):
    """Falta o arquivo de origem ou a duração do vídeo."""

    status_code = 422
    code = "clip_source_unavailable"


class ClipGenerationError(ClipError):
    """O FFmpeg não produziu um clip utilizável."""

    status_code = 500
    code = "clip_generation_failed"
