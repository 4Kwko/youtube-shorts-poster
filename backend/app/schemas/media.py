"""Contratos da camada de mídia.

Todos os campos são opcionais porque o ffprobe legitimamente omite parte deles
dependendo do container (bitrate ausente em alguns MKV, sem faixa de áudio,
altura ausente em stream corrompida). O consumidor precisa tratar a ausência
em vez de assumir um valor inventado aqui.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MediaInfo(BaseModel):
    duration_seconds: float | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    video_codec: str | None = None
    audio_codec: str | None = None
    bitrate_bps: int | None = Field(default=None, ge=0)
    container: str | None = Field(default=None, description="format_name reportado pelo ffprobe.")

    @property
    def has_video(self) -> bool:
        return self.video_codec is not None

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None

    @property
    def is_vertical(self) -> bool:
        return self.width is not None and self.height is not None and self.height > self.width
