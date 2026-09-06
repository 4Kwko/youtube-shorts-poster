"""Progresso da ingestão.

Fronteira deliberadamente burra: a ingestão só anuncia estágio e percentual
aproximado. Quem persiste isso (worker, handler) é problema de outra camada —
esta não conhece banco nem SQLAlchemy.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class IngestStage(StrEnum):
    STARTING = "starting"
    DOWNLOADING = "downloading"
    PROBING = "probing"
    FINALIZING = "finalizing"
    COMPLETED = "completed"


# Percentuais são marcos grosseiros, não medição real do download.
STAGE_PROGRESS: dict[IngestStage, int] = {
    IngestStage.STARTING: 5,
    IngestStage.DOWNLOADING: 10,
    IngestStage.PROBING: 80,
    IngestStage.FINALIZING: 95,
    IngestStage.COMPLETED: 100,
}


class ProgressCallback(Protocol):
    def __call__(self, stage: IngestStage, progress: int) -> None: ...


def noop_progress(stage: IngestStage, progress: int) -> None:
    return None
