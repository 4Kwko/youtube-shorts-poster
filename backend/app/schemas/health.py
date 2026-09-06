"""Schemas do health check."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DependencyStatus(BaseModel):
    """Disponibilidade de dependências externas.

    Apenas booleanos: versão e caminho do binário são detalhes do servidor e
    ficam no log de startup, não na resposta pública.
    """

    ffmpeg: bool = False
    ffprobe: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    name: str = Field(description="Nome da aplicação.")
    version: str
    environment: str
    uptime_seconds: float = Field(ge=0)
    dependencies: DependencyStatus = Field(default_factory=DependencyStatus)
