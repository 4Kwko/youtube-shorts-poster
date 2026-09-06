"""Recorte do transcript global para o intervalo de um clip.

Função pura: não toca disco, banco nem FFmpeg, e nunca modifica o transcript
global recebido.
"""

from __future__ import annotations

from app.schemas.transcript import TranscriptResult, TranscriptSegment, TranscriptWord

_PRECISION = 3


def _localize(value: float, start: float, duration: float) -> float:
    """Converte timestamp global em local, preso ao intervalo [0, duration]."""
    return round(min(max(value - start, 0.0), duration), _PRECISION)


def _overlaps(item_start: float, item_end: float, start: float, end: float) -> bool:
    # Fronteira exata não conta como sobreposição: uma palavra que termina
    # exatamente onde o clip começa pertence ao clip anterior.
    return item_start < end and item_end > start


def slice_transcript(
    transcript: TranscriptResult, start_time: float, end_time: float
) -> TranscriptResult:
    """Transcrição local ao clip, com timestamps recomeçando em zero.

    Segmentos e palavras que atravessam a fronteira são mantidos e recortados;
    o que estiver inteiramente fora é descartado. Quando um segmento é cortado
    ao meio, seu texto é reconstruído a partir das palavras que sobraram — usar
    o texto original traria fala que não está no clip.
    """
    if end_time <= start_time:
        raise ValueError("end_time deve ser maior que start_time.")

    duration = round(end_time - start_time, _PRECISION)
    segments: list[TranscriptSegment] = []

    for segment in transcript.segments:
        if not _overlaps(segment.start, segment.end, start_time, end_time):
            continue

        words = [
            TranscriptWord(
                start=_localize(word.start, start_time, duration),
                end=_localize(word.end, start_time, duration),
                word=word.word,
            )
            for word in segment.words
            if _overlaps(word.start, word.end, start_time, end_time)
        ]

        truncated = segment.start < start_time or segment.end > end_time
        if truncated and segment.words:
            text = " ".join(word.word for word in words).strip()
        else:
            text = segment.text

        if not text and not words:
            continue

        segments.append(
            TranscriptSegment(
                start=_localize(segment.start, start_time, duration),
                end=_localize(segment.end, start_time, duration),
                text=text,
                words=words,
            )
        )

    return TranscriptResult(
        version=transcript.version,
        language=transcript.language,
        language_probability=transcript.language_probability,
        duration=duration,
        segments=segments,
    )
