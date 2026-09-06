"""Erros da exportação para a pasta escolhida pelo usuário."""

from __future__ import annotations

from app.core.errors import AppError


class ExportError(AppError):
    status_code = 500
    code = "export_error"


class InvalidOutputDirectoryError(ExportError):
    """A pasta de saída não é utilizável."""

    status_code = 422
    code = "invalid_output_directory"


class ExportFailedError(ExportError):
    """A cópia de um ou mais clips falhou."""

    status_code = 500
    code = "export_failed"
