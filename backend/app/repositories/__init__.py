"""Repositories: acesso a dados isolado da lógica de negócio."""

from __future__ import annotations

from app.repositories.clip import ClipRepository
from app.repositories.job import JobRepository
from app.repositories.mappers import source_file_key, video_metadata_from_source
from app.repositories.transcript import TranscriptRepository
from app.repositories.video import VideoMetadata, VideoRepository

__all__ = [
    "ClipRepository",
    "JobRepository",
    "TranscriptRepository",
    "VideoMetadata",
    "VideoRepository",
    "source_file_key",
    "video_metadata_from_source",
]
