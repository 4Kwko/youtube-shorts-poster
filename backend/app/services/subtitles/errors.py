"""Erros da camada de legendas."""

from __future__ import annotations

from app.core.errors import AppError


class SubtitleError(AppError):
    status_code = 500
    code = "subtitle_error"


class SubtitleGenerationError(SubtitleError):
    """Não foi possível produzir o arquivo de legenda."""

    status_code = 500
    code = "subtitle_generation_failed"
