"""Contrato do downloader.

O serviço de ingestão conversa apenas com este protocolo. Trocar ou adicionar
um mecanismo de download (outro provider, uma API oficial) é fornecer outra
implementação e outra factory — nada mais na camada muda.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings
from app.services.ingest.urls import ValidatedVideoURL


class VideoDownloader(Protocol):
    def preflight(self) -> dict[str, Any]:
        """Metadata sem baixar mídia. Usada para recusar antes de gastar banda."""
        ...

    def download(self) -> dict[str, Any]:
        """Baixa o vídeo para o workspace e devolve a metadata final."""
        ...


DownloaderFactory = Callable[[Settings, ValidatedVideoURL, Path], VideoDownloader]
