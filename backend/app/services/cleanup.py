"""Remoção dos arquivos internos de um vídeo.

Só toca subdiretórios conhecidos de `storage/`. A pasta de exportação escolhida
pelo usuário nunca entra aqui: excluir um projeto não pode apagar os MP4 que
ele já publicou.
"""

from __future__ import annotations

import logging
import shutil

from app.core.config import Settings
from app.utils.paths import is_inside, resolve_storage_path

logger = logging.getLogger(__name__)

# Cada um guarda um diretório por vídeo.
VIDEO_SUBDIRS = ("downloads", "clips", "renders", "subtitles", "transcripts", "thumbnails")


def purge_video_files(settings: Settings, video_id: str) -> list[str]:
    """Apaga os diretórios internos do vídeo. Devolve o que foi removido.

    Defensivo por construção: o caminho é montado pelo helper de storage e
    conferido com `is_inside` antes de qualquer remoção. Falha em um
    subdiretório não impede os outros.
    """
    removed: list[str] = []

    for subdir in VIDEO_SUBDIRS:
        try:
            directory = resolve_storage_path(settings, subdir, video_id)
        except ValueError:
            logger.warning("Caminho inválido ao limpar", extra={"subdir": subdir})
            continue

        root = settings.storage_path(subdir)
        if not is_inside(root, directory) or not directory.exists():
            continue

        try:
            shutil.rmtree(directory)
            removed.append(subdir)
        except OSError:
            logger.exception("Falha ao remover diretório do vídeo", extra={"subdir": subdir})

    return removed
