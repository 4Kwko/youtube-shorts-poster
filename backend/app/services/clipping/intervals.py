"""Cálculo dos intervalos de corte.

Função pura: só aritmética sobre a duração. Testável sem FFmpeg, sem disco e
sem banco.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.clipping.errors import ClipSourceUnavailableError

# Um resto muito curto vira um clip inútil (e às vezes sem keyframe). Abaixo
# disso ele é absorvido pelo clip anterior em vez de virar arquivo próprio.
DEFAULT_MIN_CLIP_SECONDS = 1.0

# Duas casas bastam para corte de vídeo e evitam ruído de ponto flutuante
# acumulado ao somar a duração repetidamente.
_PRECISION = 3


@dataclass(frozen=True, slots=True)
class ClipInterval:
    sequence: int
    start_time: float
    end_time: float

    @property
    def duration(self) -> float:
        return round(self.end_time - self.start_time, _PRECISION)


def compute_intervals(
    video_duration: float,
    clip_duration: float,
    *,
    min_clip_duration: float = DEFAULT_MIN_CLIP_SECONDS,
) -> list[ClipInterval]:
    """Fatia `video_duration` em trechos sequenciais de `clip_duration`.

    O último trecho pode ser menor. Vídeo mais curto que `clip_duration` vira
    um único clip com a duração inteira.
    """
    if video_duration <= 0:
        raise ClipSourceUnavailableError("Duração do vídeo desconhecida ou inválida.")
    if clip_duration <= 0:
        raise ValueError("clip_duration deve ser maior que zero.")

    intervals: list[ClipInterval] = []
    start = 0.0
    sequence = 0

    while start < video_duration:
        end = min(round(start + clip_duration, _PRECISION), video_duration)
        intervals.append(
            ClipInterval(
                sequence=sequence,
                start_time=round(start, _PRECISION),
                end_time=round(end, _PRECISION),
            )
        )
        start = end
        sequence += 1

    # Resto curto demais: estende o clip anterior em vez de criar um fragmento.
    if len(intervals) > 1 and intervals[-1].duration < min_clip_duration:
        tail = intervals.pop()
        previous = intervals.pop()
        intervals.append(
            ClipInterval(
                sequence=previous.sequence,
                start_time=previous.start_time,
                end_time=tail.end_time,
            )
        )

    return intervals
