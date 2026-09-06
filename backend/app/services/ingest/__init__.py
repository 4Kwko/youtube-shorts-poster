"""Camada de ingestão de vídeos por URL."""

from __future__ import annotations

from app.services.ingest.errors import (
    DownloadTimeoutError,
    IngestError,
    InvalidVideoURLError,
    LiveStreamNotSupportedError,
    UnsupportedVideoURLError,
    VideoDownloadError,
    VideoTooLargeError,
    VideoTooLongError,
    VideoUnavailableError,
)
from app.services.ingest.providers import PROVIDERS, Provider, supported_hosts
from app.services.ingest.service import import_video, new_video_id, workspace_for
from app.services.ingest.urls import ValidatedVideoURL, validate_video_url

__all__ = [
    "PROVIDERS",
    "DownloadTimeoutError",
    "IngestError",
    "InvalidVideoURLError",
    "LiveStreamNotSupportedError",
    "Provider",
    "UnsupportedVideoURLError",
    "ValidatedVideoURL",
    "VideoDownloadError",
    "VideoTooLargeError",
    "VideoTooLongError",
    "VideoUnavailableError",
    "import_video",
    "new_video_id",
    "supported_hosts",
    "validate_video_url",
    "workspace_for",
]
