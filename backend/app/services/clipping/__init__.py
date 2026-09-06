"""Geração de clips a partir de um vídeo importado."""

from __future__ import annotations

from app.services.clipping.clipper import ClipArtifact, FixedClipper, clip_filename
from app.services.clipping.errors import (
    ClipError,
    ClipGenerationError,
    ClipSourceUnavailableError,
)
from app.services.clipping.intervals import ClipInterval, compute_intervals

__all__ = [
    "ClipArtifact",
    "ClipError",
    "ClipGenerationError",
    "ClipInterval",
    "ClipSourceUnavailableError",
    "FixedClipper",
    "clip_filename",
    "compute_intervals",
]
