"""Adaptador do yt-dlp.

Este é o único módulo do projeto que importa `yt_dlp`. Tudo que sai daqui já
está em termos do domínio: dicionários de metadata e exceções de
`ingest.errors`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

from app.core.config import Settings
from app.services.ingest.errors import (
    DownloadTimeoutError,
    VideoDownloadError,
    VideoTooLargeError,
    VideoUnavailableError,
)
from app.services.ingest.urls import ValidatedVideoURL
from app.services.media.binaries import require_ffmpeg

logger = logging.getLogger(__name__)

SOURCE_STEM = "source"

# Trechos que o yt-dlp usa para indisponibilidade do conteúdo, e não falha
# técnica nossa. A distinção muda o status HTTP e a orientação ao usuário.
_UNAVAILABLE_MARKERS = (
    "private",
    "unavailable",
    "removed",
    "deleted",
    "does not exist",
    "not available",
    "no longer available",
    "sign in to confirm",
    "age-restricted",
    "age restricted",
    "members-only",
    "copyright",
    "blocked",
    "geo restricted",
    "available in your country",
    "not made this video available",
    "this video is not",
)

_SIZE_LIMIT_MARKERS = ("file is larger than max-filesize",)


class _TimeoutSignal(Exception):
    """Sinaliza estouro de relógio de parede para interromper o yt-dlp."""


class _YtdlpLogger:
    """Redireciona a saída do yt-dlp para o logging da aplicação.

    Sem isso o yt-dlp escreve direto em stdout/stderr, fora do formato
    estruturado e sem o request_id.
    """

    def debug(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.error("yt-dlp: %s", msg)


def build_format_selector(max_height: int) -> str:
    """Seletor de formato tolerante a provedores sem MP4/H.264 pronto.

    A ordem tenta primeiro a combinação já compatível com o processamento
    posterior e vai relaxando: nunca exige uma combinação impossível, e deixa
    o merge para o FFmpeg quando for preciso.
    """
    return (
        f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={max_height}]+bestaudio/"
        f"best[height<={max_height}]/"
        "bestvideo+bestaudio/best"
    )


def build_ydl_options(
    settings: Settings,
    validated: ValidatedVideoURL,
    workspace: Path,
    *,
    ffmpeg_path: str | None = None,
    download: bool = True,
) -> dict[str, Any]:
    """Opções do yt-dlp.

    Pontos que não são preferência e sim requisito de segurança:
    o nome do arquivo é fixo (o título do provedor nunca chega ao path),
    `allowed_extractors` impede o extractor genérico de buscar host arbitrário,
    e a lista de postprocessors não é influenciável pelo input.
    """
    options: dict[str, Any] = {
        # Nome fixo: só a extensão vem de fora, e o yt-dlp a restringe a um
        # conjunto conhecido de containers.
        "outtmpl": {"default": f"{SOURCE_STEM}.%(ext)s"},
        "paths": {"home": str(workspace), "temp": str(workspace)},
        "format": build_format_selector(settings.max_video_height),
        "merge_output_format": "mp4",
        # Um vídeo, sempre. Cobre URL com ?list= mesmo que a limpeza falhe.
        "noplaylist": True,
        "playlist_items": "1",
        "allowed_extractors": list(validated.provider.extractor_patterns),
        # Nada além da mídia.
        "writesubtitles": False,
        "writeautomaticsub": False,
        "writethumbnail": False,
        "writeinfojson": False,
        "writedescription": False,
        "writeannotations": False,
        "getcomments": False,
        "postprocessors": [],
        # O yt-dlp não executa nada externo além do FFmpeg que apontamos.
        "cachedir": False,
        "call_home": False,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": True,
        "continuedl": False,
        "noprogress": True,
        "quiet": True,
        "no_color": True,
        "logger": _YtdlpLogger(),
        "socket_timeout": settings.download_socket_timeout_seconds,
        "retries": settings.download_retries,
        "fragment_retries": settings.download_retries,
        # Corta cedo quando o próprio yt-dlp já sabe o tamanho.
        "max_filesize": settings.max_video_file_size_bytes,
        "skip_download": not download,
    }

    if ffmpeg_path is not None:
        options["ffmpeg_location"] = ffmpeg_path

    return options


def _message_matches(message: str, markers: tuple[str, ...]) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in markers)


def _translate(exc: Exception, *, url_for_log: str) -> Exception:
    """Converte exceção do yt-dlp em erro do domínio.

    A mensagem original vai só para o log: pode conter URL interna do CDN,
    cookie de sessão ou detalhe do extractor.
    """
    message = str(exc)
    logger.warning(
        "yt-dlp falhou",
        extra={"error_type": type(exc).__name__, "detail": message[:500], "url": url_for_log},
    )

    if isinstance(exc, UnsupportedError):
        return VideoUnavailableError("Não foi possível processar este vídeo.")
    if _message_matches(message, _SIZE_LIMIT_MARKERS):
        return VideoTooLargeError("O vídeo excede o tamanho máximo permitido.")
    if _message_matches(message, _UNAVAILABLE_MARKERS):
        return VideoUnavailableError("O vídeo não está disponível para download.")
    return VideoDownloadError("Falha ao importar o vídeo.")


class YtDlpDownloader:
    """Implementação de `VideoDownloader` sobre a API Python do yt-dlp.

    Usar a API Python em vez de subprocess evita montar linha de comando com
    dado externo e dá acesso direto ao dicionário de metadata.
    """

    def __init__(self, settings: Settings, validated: ValidatedVideoURL, workspace: Path) -> None:
        self._settings = settings
        self._validated = validated
        self._workspace = workspace
        # O merge de faixas separadas depende do FFmpeg; falhar aqui é melhor
        # do que descobrir no meio do download.
        self._ffmpeg_path = require_ffmpeg()

    def _run(self, *, download: bool) -> dict[str, Any]:
        options = build_ydl_options(
            self._settings,
            self._validated,
            self._workspace,
            ffmpeg_path=self._ffmpeg_path,
            download=download,
        )

        if download:
            options["progress_hooks"] = [self._make_timeout_hook()]

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(self._validated.url, download=download)
        except _TimeoutSignal as exc:
            raise DownloadTimeoutError("O download excedeu o tempo limite.") from exc
        except (DownloadError, ExtractorError, UnsupportedError) as exc:
            # DownloadError embrulha o timeout quando ele sobe de dentro do hook.
            if isinstance(exc.__cause__, _TimeoutSignal):
                raise DownloadTimeoutError("O download excedeu o tempo limite.") from exc
            raise _translate(exc, url_for_log=self._validated.url) from exc
        except OSError as exc:
            logger.exception("Falha de I/O durante o download")
            raise VideoDownloadError("Falha ao gravar o vídeo no servidor.") from exc

        if info is None:
            raise VideoDownloadError("Falha ao importar o vídeo.")

        # URL de playlist que escapou da limpeza: fica só a primeira entrada.
        entries = info.get("entries") if isinstance(info, dict) else None
        if isinstance(entries, list):
            if not entries:
                raise VideoUnavailableError("Nenhum vídeo encontrado nesta URL.")
            first = entries[0]
            if not isinstance(first, dict):
                raise VideoDownloadError("Metadata inesperada ao importar o vídeo.")
            return first

        return dict(info)

    def _make_timeout_hook(self) -> Any:
        """Relógio de parede.

        O `socket_timeout` do yt-dlp cobre inatividade de socket, não a duração
        total: um vídeo enorme baixando devagar nunca dispararia. O hook é
        chamado a cada fragmento, então serve de ponto de checagem.
        """
        deadline = time.monotonic() + self._settings.download_timeout_seconds

        def hook(status: dict[str, Any]) -> None:
            if time.monotonic() > deadline:
                raise _TimeoutSignal

        return hook

    def preflight(self) -> dict[str, Any]:
        return self._run(download=False)

    def download(self) -> dict[str, Any]:
        return self._run(download=True)


def create_downloader(
    settings: Settings, validated: ValidatedVideoURL, workspace: Path
) -> YtDlpDownloader:
    return YtDlpDownloader(settings, validated, workspace)
