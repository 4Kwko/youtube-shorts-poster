"""Transcrição do vídeo original."""

from __future__ import annotations

from app.services.transcription.backend import (
    load_model,
    normalize_segments,
    reset_model_cache,
    transcribe_file,
)
from app.services.transcription.errors import (
    TranscriptionError,
    TranscriptionFailedError,
    TranscriptionModelUnavailableError,
    TranscriptUnavailableError,
)
from app.services.transcription.storage import (
    TRANSCRIPTS_SUBDIR,
    delete_transcript,
    read_transcript,
    transcript_file_key,
    write_transcript,
)

__all__ = [
    "TRANSCRIPTS_SUBDIR",
    "TranscriptUnavailableError",
    "TranscriptionError",
    "TranscriptionFailedError",
    "TranscriptionModelUnavailableError",
    "delete_transcript",
    "load_model",
    "normalize_segments",
    "read_transcript",
    "reset_model_cache",
    "transcribe_file",
    "transcript_file_key",
    "write_transcript",
]
