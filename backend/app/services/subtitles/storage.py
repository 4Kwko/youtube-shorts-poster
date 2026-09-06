"""Persistência dos arquivos `.ass`.

O ASS é regenerável a partir do transcript, então sobrescrever é sempre seguro.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import Settings
from app.utils.paths import resolve_storage_path

logger = logging.getLogger(__name__)

SUBTITLES_SUBDIR = "subtitles"


def subtitle_file_key(video_id: str, sequence: int) -> str:
    return f"{video_id}/{sequence:03d}.ass"


def subtitle_path(settings: Settings, video_id: str, sequence: int) -> Path:
    return resolve_storage_path(
        settings, SUBTITLES_SUBDIR, *subtitle_file_key(video_id, sequence).split("/")
    )


def write_subtitle(settings: Settings, video_id: str, sequence: int, content: str) -> Path:
    """Grava o `.ass` e devolve o caminho interno."""
    path = subtitle_path(settings, video_id, sequence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def delete_subtitles(settings: Settings, video_id: str) -> None:
    directory = resolve_storage_path(settings, SUBTITLES_SUBDIR, video_id)
    if not directory.exists():
        return
    for path in directory.glob("*.ass"):
        path.unlink(missing_ok=True)
