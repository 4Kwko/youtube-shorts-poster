"""Contexto entregue a um handler de job."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.enums import JobType


@dataclass(frozen=True, slots=True)
class JobContext:
    """Tudo que um handler precisa, sem Session compartilhada.

    O handler recebe a *factory*, não uma sessão aberta: cada passo abre a sua
    própria transação curta, para que o progresso fique visível durante um job
    longo em vez de esperar o commit final.
    """

    settings: Settings
    session_factory: sessionmaker[Session]
    job_id: str
    video_id: str
    job_type: JobType
