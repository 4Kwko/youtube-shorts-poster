"""Camada de interação com FFmpeg e FFprobe."""

from __future__ import annotations

from app.services.media.binaries import (
    BinaryStatus,
    MediaBinary,
    clear_binary_cache,
    get_binary_status,
    require_ffmpeg,
    require_ffprobe,
)
from app.services.media.errors import (
    FFmpegNotInstalledError,
    FFprobeNotInstalledError,
    InvalidMediaFileError,
    MediaError,
    MediaProbeError,
    MediaProcessingError,
)
from app.services.media.probe import parse_probe_payload, probe_file, probe_storage_file

__all__ = [
    "BinaryStatus",
    "FFmpegNotInstalledError",
    "FFprobeNotInstalledError",
    "InvalidMediaFileError",
    "MediaBinary",
    "MediaError",
    "MediaProbeError",
    "MediaProcessingError",
    "clear_binary_cache",
    "get_binary_status",
    "parse_probe_payload",
    "probe_file",
    "probe_storage_file",
    "require_ffmpeg",
    "require_ffprobe",
]
