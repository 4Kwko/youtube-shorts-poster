"""Exceções de domínio.

Toda falha esperada deve virar uma subclasse de `AppError`, com um `code`
estável que o frontend possa tratar programaticamente. Falhas inesperadas
sobem como exceção normal e viram 500 opaco no handler global.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class InvalidInputError(AppError):
    status_code = 422
    code = "invalid_input"


class ExternalServiceError(AppError):
    """Falha ao acionar um recurso externo (download, ASR, FFmpeg)."""

    status_code = 502
    code = "external_service_error"
