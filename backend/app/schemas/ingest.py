"""Contratos da camada de ingestão.

`local_filename` é apenas o nome do arquivo dentro do workspace do vídeo,
nunca um caminho. O caminho absoluto existe só dentro da camada de serviço e
é reconstruído a partir de `id` + `local_filename` por quem tem as settings.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VideoSourceInfo(BaseModel):
    id: str = Field(description="Identificador interno gerado pela aplicação.")
    source_url: str
    provider: str
    provider_video_id: str | None = None
    title: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)
    local_filename: str = Field(description="Nome do arquivo dentro do workspace do vídeo.")
