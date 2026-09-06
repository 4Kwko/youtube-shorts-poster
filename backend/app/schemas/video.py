"""Contratos HTTP de Video.

Schemas separados do ORM de propósito: o que entra na resposta é decidido
aqui, campo a campo. `source_file_key` e qualquer referência de disco nunca
aparecem.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import MAX_BATCH_VIDEOS
from app.models.enums import JobType, SourceType, VideoStatus
from app.schemas.common import UTCDatetime
from app.schemas.settings import VideoSettings


class VideoCreateRequest(BaseModel):
    url: str = Field(
        max_length=2048,
        description="URL http(s) de um provedor suportado.",
        examples=["https://www.youtube.com/watch?v=..."],
    )
    settings: VideoSettings = Field(
        default_factory=VideoSettings,
        description="Configuração de processamento. Omitida, usa os defaults.",
    )


class VideoBatchRequest(BaseModel):
    urls: list[str] = Field(
        min_length=1,
        max_length=MAX_BATCH_VIDEOS,
        description="URLs a processar. Cada uma vira um projeto próprio.",
    )
    settings: VideoSettings = Field(
        default_factory=VideoSettings,
        description="Snapshot aplicado a todos os vídeos deste envio.",
    )


class LocalImportRequest(BaseModel):
    paths: list[str] = Field(
        min_length=1,
        max_length=MAX_BATCH_VIDEOS,
        description="Caminhos absolutos vindos do seletor nativo do aplicativo.",
    )
    settings: VideoSettings = Field(
        default_factory=VideoSettings,
        description="Snapshot aplicado a todos os arquivos deste envio.",
    )


class VideoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_url: str | None = None
    source_type: SourceType
    provider: str
    title: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    status: VideoStatus
    settings: VideoSettings
    progress: int
    current_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class VideoSummary(BaseModel):
    """Item da lista de projetos: resumo, sem clips nem caminhos internos."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_url: str | None = None
    source_type: SourceType
    provider: str
    title: str | None = None
    duration: float | None = None
    status: VideoStatus
    progress: int
    current_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    settings: VideoSettings
    clip_count: int = 0
    has_thumbnail: bool = False
    created_at: UTCDatetime
    updated_at: UTCDatetime


class VideoListResponse(BaseModel):
    items: list[VideoSummary]
    total: int
    limit: int
    offset: int


class RetryResponse(BaseModel):
    video_id: str
    job_id: str
    job_type: JobType
    status: VideoStatus


class VideoBatchResponse(BaseModel):
    videos: list[VideoResponse]
