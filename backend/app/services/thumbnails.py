"""Miniatura do projeto, extraída do primeiro clip renderizado.

Gerada uma vez, no fim da renderização — nunca durante uma requisição HTTP.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import Settings
from app.services.media.binaries import require_ffmpeg
from app.services.media.errors import MediaError
from app.services.media.runner import run_command
from app.utils.paths import resolve_storage_path

logger = logging.getLogger(__name__)

THUMBNAILS_SUBDIR = "thumbnails"
THUMBNAIL_FILENAME = "project.jpg"
# Pequena de propósito: é um card de lista, não um player.
THUMBNAIL_WIDTH = 360
THUMBNAIL_TIMEOUT_SECONDS = 30.0


def thumbnail_path(settings: Settings, video_id: str) -> Path:
    return resolve_storage_path(settings, THUMBNAILS_SUBDIR, video_id, THUMBNAIL_FILENAME)


def generate_thumbnail(settings: Settings, video_id: str, source: Path) -> Path | None:
    """Extrai um frame do clip e grava a miniatura. `None` se não der.

    Falha aqui nunca derruba o job: a lista mostra um placeholder.
    """
    if not source.is_file():
        return None

    output = thumbnail_path(settings, video_id)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        ffmpeg = require_ffmpeg()
    except MediaError:
        return None

    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        # Meio segundo à frente: o primeiro frame costuma ser preto.
        "-ss",
        "0.5",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={THUMBNAIL_WIDTH}:-2",
        "-q:v",
        "6",
        "-y",
        str(output),
    ]

    try:
        result = run_command(args, timeout=THUMBNAIL_TIMEOUT_SECONDS)
    except MediaError:
        logger.warning("Falha ao gerar miniatura", extra={"video_id": video_id})
        return None

    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        logger.warning("Miniatura não produzida", extra={"video_id": video_id})
        return None

    return output
