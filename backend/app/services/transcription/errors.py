"""Erros da camada de transcrição."""

from __future__ import annotations

from app.core.errors import AppError


class TranscriptionError(AppError):
    status_code = 500
    code = "transcription_error"


class TranscriptionModelUnavailableError(TranscriptionError):
    """O modelo do Whisper não pôde ser carregado (ausente, corrompido, sem disco)."""

    status_code = 503
    code = "transcription_model_unavailable"


class TranscriptionFailedError(TranscriptionError):
    """O Whisper rodou mas não produziu uma transcrição utilizável."""

    status_code = 500
    code = "transcription_failed"


class TranscriptUnavailableError(TranscriptionError):
    """O arquivo de transcrição não existe ou não pôde ser lido."""

    status_code = 404
    code = "transcript_unavailable"
