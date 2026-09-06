"""Exceções da camada de mídia.

Herdam de `AppError` para reaproveitar o envelope de erro já existente. As
mensagens são escritas assumindo que chegarão ao cliente: nunca contêm caminho
de arquivo, linha de comando ou stderr do processo — esses ficam apenas no log.
"""

from __future__ import annotations

from app.core.errors import AppError


class MediaError(AppError):
    """Base de todas as falhas da camada de mídia."""

    status_code = 500
    code = "media_error"


class MediaProcessingError(MediaError):
    """Um processo externo de mídia falhou, expirou ou não pôde ser iniciado."""

    status_code = 500
    code = "media_processing_error"


class BinaryNotInstalledError(MediaProcessingError):
    """Um binário externo obrigatório não foi encontrado no ambiente."""

    status_code = 503
    code = "media_binary_unavailable"


class FFmpegNotInstalledError(BinaryNotInstalledError):
    code = "ffmpeg_unavailable"

    def __init__(self) -> None:
        super().__init__("FFmpeg não está disponível no servidor.")


class FFprobeNotInstalledError(BinaryNotInstalledError):
    code = "ffprobe_unavailable"

    def __init__(self) -> None:
        super().__init__("FFprobe não está disponível no servidor.")


class InvalidMediaFileError(MediaError):
    """O caminho não aponta para um arquivo legível dentro do storage."""

    status_code = 422
    code = "invalid_media_file"


class MediaProbeError(MediaError):
    """O ffprobe rodou mas não produziu metadata utilizável."""

    status_code = 422
    code = "media_probe_failed"
