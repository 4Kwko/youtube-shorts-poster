"""Formato único de erro da API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(description="Identificador estável do erro, para tratamento no cliente.")
    message: str = Field(description="Mensagem legível. Nunca contém caminhos internos.")
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str | None = None
