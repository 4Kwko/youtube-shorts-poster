"""Adaptador do faster-whisper.

Único módulo que conhece `faster_whisper`. O import acontece dentro da função
de carga, não no topo: a aplicação precisa subir mesmo sem a biblioteca ou sem
modelo baixado, e um erro aí deve virar erro de transcrição, não falha de
import do FastAPI.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings
from app.schemas.transcript import TranscriptResult, TranscriptSegment, TranscriptWord
from app.services.transcription.errors import (
    TranscriptionFailedError,
    TranscriptionModelUnavailableError,
)

logger = logging.getLogger(__name__)


class WhisperModel(Protocol):
    def transcribe(self, audio: str, **kwargs: Any) -> tuple[Any, Any]: ...


# O modelo custa segundos para carregar e centenas de MB de RAM. Uma instância
# por processo de worker, reutilizada entre jobs.
_model_lock = threading.Lock()
_model_cache: dict[tuple[str, str, str], WhisperModel] = {}


def _model_key(settings: Settings) -> tuple[str, str, str]:
    return (settings.whisper_model, settings.whisper_device, settings.whisper_compute_type)


def load_model(settings: Settings) -> WhisperModel:
    """Carrega (ou reaproveita) o modelo. Baixa na primeira chamada, se preciso."""
    key = _model_key(settings)

    with _model_lock:
        cached = _model_cache.get(key)
        if cached is not None:
            return cached

        try:
            from faster_whisper import WhisperModel as FasterWhisperModel
        except ImportError as exc:
            raise TranscriptionModelUnavailableError(
                "Transcrição indisponível no servidor."
            ) from exc

        logger.info(
            "Carregando modelo de transcrição",
            extra={"model": key[0], "device": key[1], "compute_type": key[2]},
        )
        try:
            model: WhisperModel = FasterWhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
        except Exception as exc:
            logger.exception("Falha ao carregar o modelo de transcrição")
            raise TranscriptionModelUnavailableError(
                "Não foi possível carregar o modelo de transcrição."
            ) from exc

        _model_cache[key] = model
        return model


def reset_model_cache() -> None:
    """Descarta o modelo em memória. Usado em testes e ao trocar de configuração."""
    with _model_lock:
        _model_cache.clear()


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_segments(raw_segments: Any) -> list[TranscriptSegment]:
    """Converte os segmentos do faster-whisper no formato interno.

    O faster-whisper devolve um gerador de objetos com atributos; consumir aqui
    é o que dispara a transcrição de fato.
    """
    segments: list[TranscriptSegment] = []

    for raw in raw_segments:
        start = _as_float(getattr(raw, "start", None))
        end = _as_float(getattr(raw, "end", None))
        text = getattr(raw, "text", "")
        if start is None or end is None or not isinstance(text, str):
            continue

        words: list[TranscriptWord] = []
        for raw_word in getattr(raw, "words", None) or []:
            word_start = _as_float(getattr(raw_word, "start", None))
            word_end = _as_float(getattr(raw_word, "end", None))
            word_text = getattr(raw_word, "word", None)
            if word_start is None or word_end is None or not isinstance(word_text, str):
                continue
            words.append(TranscriptWord(start=word_start, end=word_end, word=word_text.strip()))

        segments.append(TranscriptSegment(start=start, end=end, text=text.strip(), words=words))

    return segments


def transcribe_file(settings: Settings, source: Path) -> TranscriptResult:
    """Transcreve um arquivo de mídia com timestamps por palavra.

    O faster-whisper decodifica o container com o próprio FFmpeg embutido, então
    não geramos WAV intermediário: seria um passo de I/O e disco sem ganho.
    """
    model = load_model(settings)

    try:
        raw_segments, info = model.transcribe(
            str(source),
            beam_size=settings.whisper_beam_size,
            # Sem isto não há timestamps por palavra, e legenda por palavra
            # ficaria impossível sem re-transcrever tudo.
            word_timestamps=True,
        )
        segments = normalize_segments(raw_segments)
    except Exception as exc:
        logger.exception("Falha durante a transcrição", extra={"file": source.name})
        raise TranscriptionFailedError("Falha ao transcrever o áudio do vídeo.") from exc

    return TranscriptResult(
        language=getattr(info, "language", None),
        language_probability=_as_float(getattr(info, "language_probability", None)),
        duration=_as_float(getattr(info, "duration", None)),
        segments=segments,
    )
