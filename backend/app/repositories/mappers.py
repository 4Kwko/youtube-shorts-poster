"""Mapeamento entre resultado da ingestão e metadata persistida.

Fica no lado da persistência de propósito: a camada de ingestão não conhece o
banco, e este módulo depende apenas do schema `VideoSourceInfo`.
"""

from __future__ import annotations

from app.repositories.video import VideoMetadata
from app.schemas.ingest import VideoSourceInfo


def source_file_key(video_id: str, local_filename: str) -> str:
    """Chave relativa ao subdiretório de downloads."""
    return f"{video_id}/{local_filename}"


def video_metadata_from_source(info: VideoSourceInfo) -> VideoMetadata:
    return VideoMetadata(
        title=info.title,
        provider_video_id=info.provider_video_id,
        duration=info.duration_seconds,
        width=info.width,
        height=info.height,
        fps=info.fps,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
        container=info.container,
        file_size=info.file_size_bytes,
        source_file_key=source_file_key(info.id, info.local_filename),
    )
