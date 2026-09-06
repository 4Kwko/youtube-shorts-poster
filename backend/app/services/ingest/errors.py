"""Exceções da camada de ingestão.

Herdam de `AppError` para reaproveitar o envelope de erro do projeto. As
mensagens assumem que chegarão ao cliente: nunca contêm mensagem crua do
yt-dlp, caminho interno ou detalhe do extractor — isso fica só no log.
"""

from __future__ import annotations

from app.core.errors import AppError


class IngestError(AppError):
    """Base de todas as falhas de ingestão."""

    status_code = 500
    code = "ingest_error"


class InvalidVideoURLError(IngestError):
    """A string recebida não é uma URL http(s) utilizável."""

    status_code = 422
    code = "invalid_video_url"


class UnsupportedVideoURLError(IngestError):
    """A URL é válida mas o provedor não está na allowlist."""

    status_code = 422
    code = "unsupported_video_url"


class VideoUnavailableError(IngestError):
    """O vídeo existe na URL mas não pode ser acessado (privado, removido, geo)."""

    status_code = 422
    code = "video_unavailable"


class VideoDownloadError(IngestError):
    """A ingestão falhou por motivo técnico (rede, extractor, merge)."""

    status_code = 502
    code = "video_download_failed"


class VideoTooLongError(IngestError):
    """Duração acima de `MAX_VIDEO_DURATION_SECONDS`."""

    status_code = 422
    code = "video_too_long"


class VideoTooLargeError(IngestError):
    """Tamanho acima de `MAX_VIDEO_FILE_SIZE_BYTES`."""

    status_code = 422
    code = "video_too_large"


class DownloadTimeoutError(IngestError):
    """O download excedeu `DOWNLOAD_TIMEOUT_SECONDS`."""

    status_code = 504
    code = "video_download_timeout"


class LiveStreamNotSupportedError(IngestError):
    """Transmissões ao vivo não têm duração fechada e não são ingeríveis."""

    status_code = 422
    code = "live_stream_not_supported"
