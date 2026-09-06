"""Agrupamento das palavras em eventos curtos de legenda.

Função pura sobre a transcrição local. O algoritmo é deliberadamente simples:
corta por contagem de palavras, tamanho de linha, pontuação e pausa audível —
nada de análise linguística.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.transcript import TranscriptResult, TranscriptSegment, TranscriptWord

# Fim de frase: quebrar aqui deixa a leitura natural.
SENTENCE_END = (".", "!", "?", "…")
# Pausa sintática: quebra permitida, mas só se já houver palavras suficientes.
CLAUSE_END = (",", ";", ":", "—")

MIN_WORDS_BEFORE_CLAUSE_BREAK = 2


@dataclass(frozen=True, slots=True)
class SubtitleEvent:
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def _ends_with(word: str, endings: tuple[str, ...]) -> bool:
    stripped = word.rstrip("\"')]»")
    return stripped.endswith(endings)


def _event_from_words(words: list[TranscriptWord]) -> SubtitleEvent:
    return SubtitleEvent(
        start=words[0].start,
        end=words[-1].end,
        text=" ".join(word.word for word in words).strip(),
        words=list(words),
    )


def _should_break_after(
    current: list[TranscriptWord],
    word: TranscriptWord,
    next_word: TranscriptWord | None,
    *,
    max_words: int,
    max_chars: int,
    max_duration: float,
    pause_break: float,
) -> bool:
    if len(current) >= max_words:
        return True
    if _ends_with(word.word, SENTENCE_END):
        return True
    if len(current) >= MIN_WORDS_BEFORE_CLAUSE_BREAK and _ends_with(word.word, CLAUSE_END):
        return True
    if next_word is not None:
        if next_word.start - word.end >= pause_break:
            return True
        line_length = len(" ".join(w.word for w in current)) + 1 + len(next_word.word)
        if line_length > max_chars:
            return True
        if next_word.end - current[0].start > max_duration:
            return True
    return False


def _events_from_segment(
    segment: TranscriptSegment,
    *,
    max_words: int,
    max_chars: int,
    max_duration: float,
    pause_break: float,
) -> list[SubtitleEvent]:
    if not segment.words:
        # Sem timestamps por palavra sobra o segmento inteiro; melhor uma
        # legenda longa do que nenhuma.
        text = segment.text.strip()
        if not text or segment.end <= segment.start:
            return []
        return [SubtitleEvent(start=segment.start, end=segment.end, text=text)]

    events: list[SubtitleEvent] = []
    current: list[TranscriptWord] = []

    for index, word in enumerate(segment.words):
        if not word.word:
            continue
        current.append(word)
        next_word = segment.words[index + 1] if index + 1 < len(segment.words) else None

        if _should_break_after(
            current,
            word,
            next_word,
            max_words=max_words,
            max_chars=max_chars,
            max_duration=max_duration,
            pause_break=pause_break,
        ):
            events.append(_event_from_words(current))
            current = []

    if current:
        events.append(_event_from_words(current))

    return [event for event in events if event.text]


def _enforce_min_duration(
    events: list[SubtitleEvent], min_duration: float, limit: float
) -> list[SubtitleEvent]:
    """Estica eventos rápidos demais até o próximo, sem sobrepor.

    Palavras isoladas costumam durar 0.2s; nesse tempo ninguém lê. Esticar a
    exibição é preferível a fundir com o bloco seguinte, que quebraria o
    sincronismo com a fala.
    """
    adjusted: list[SubtitleEvent] = []

    for index, event in enumerate(events):
        if event.duration >= min_duration:
            adjusted.append(event)
            continue

        ceiling = events[index + 1].start if index + 1 < len(events) else limit
        end = min(round(event.start + min_duration, 3), ceiling)
        adjusted.append(
            SubtitleEvent(
                start=event.start,
                end=max(end, event.end),
                text=event.text,
                words=event.words,
            )
        )

    return adjusted


def build_events(
    transcript: TranscriptResult,
    *,
    max_words: int = 5,
    max_chars: int = 32,
    min_duration: float = 0.6,
    max_duration: float = 2.5,
    pause_break: float = 0.35,
) -> list[SubtitleEvent]:
    """Converte a transcrição local do clip em eventos de legenda."""
    events: list[SubtitleEvent] = []

    for segment in transcript.segments:
        events.extend(
            _events_from_segment(
                segment,
                max_words=max_words,
                max_chars=max_chars,
                max_duration=max_duration,
                pause_break=pause_break,
            )
        )

    limit = transcript.duration if transcript.duration is not None else float("inf")
    return _enforce_min_duration(events, min_duration, limit)
