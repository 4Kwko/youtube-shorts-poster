"""Persistência do JSON da transcrição.

Milhares de palavras por vídeo não cabem bem em linhas de SQLite. O texto vai
para o storage e o banco guarda só a metadata e a chave relativa do arquivo.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import Settings
from app.schemas.transcript import TranscriptResult
from app.services.transcription.errors import TranscriptUnavailableError
from app.utils.paths import resolve_storage_path

logger = logging.getLogger(__name__)

TRANSCRIPTS_SUBDIR = "transcripts"
TRANSCRIPT_FILENAME = "transcript.json"


def transcript_file_key(video_id: str) -> str:
    """Chave relativa ao subdiretório de transcrições."""
    return f"{video_id}/{TRANSCRIPT_FILENAME}"


def transcript_path(settings: Settings, file_key: str) -> Path:
    return resolve_storage_path(settings, TRANSCRIPTS_SUBDIR, *file_key.split("/"))


def write_transcript(settings: Settings, video_id: str, result: TranscriptResult) -> str:
    """Grava o JSON e devolve a chave relativa.

    Escrita em arquivo temporário seguida de rename: uma falha no meio nunca
    deixa um JSON truncado ocupando o lugar de um válido.
    """
    path = transcript_path(settings, transcript_file_key(video_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")

    try:
        temporary.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        logger.exception("Falha ao gravar a transcrição", extra={"video_id": video_id})
        raise

    return transcript_file_key(video_id)


def read_transcript(settings: Settings, file_key: str) -> TranscriptResult:
    path = transcript_path(settings, file_key)
    if not path.is_file():
        raise TranscriptUnavailableError("Transcrição não encontrada.")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TranscriptResult.model_validate(payload)
    except (OSError, ValueError) as exc:
        logger.exception("Transcrição ilegível", extra={"file_key": file_key})
        raise TranscriptUnavailableError("Transcrição não pôde ser lida.") from exc


def delete_transcript(settings: Settings, video_id: str) -> None:
    path = transcript_path(settings, transcript_file_key(video_id))
    path.unlink(missing_ok=True)
    path.with_suffix(".json.tmp").unlink(missing_ok=True)
