"""Acesso a dados de Job. Sem regra de negócio e sem commit."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.base import utcnow
from app.models.enums import JobStatus, JobType
from app.models.job import Job


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        video_id: str,
        job_type: JobType,
        max_attempts: int = 3,
    ) -> Job:
        job = Job(video_id=video_id, job_type=job_type, max_attempts=max_attempts)
        self._session.add(job)
        self._session.flush()
        return job

    def create_if_absent(
        self, *, video_id: str, job_type: JobType, max_attempts: int = 3
    ) -> Job | None:
        """Cria o job só se ainda não houver um equivalente para este vídeo.

        "Equivalente" é um job do mesmo tipo pendente ou já concluído com
        sucesso. Um job que falhou de vez não bloqueia: reprocessar o vídeo
        deve poder recriá-lo. É a proteção mínima contra encadeamento repetido
        virar cadeia infinita de jobs.
        """
        blocking = {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED}
        existing = select(Job.id).where(
            Job.video_id == video_id,
            Job.job_type == job_type,
            Job.status.in_(blocking),
        )
        if self._session.execute(existing).first() is not None:
            return None

        return self.create(video_id=video_id, job_type=job_type, max_attempts=max_attempts)

    def has_pending(self, video_id: str, job_type: JobType) -> bool:
        stmt = select(Job.id).where(
            Job.video_id == video_id,
            Job.job_type == job_type,
            Job.status.in_({JobStatus.QUEUED, JobStatus.RUNNING}),
        )
        return self._session.execute(stmt).first() is not None

    def get_by_id(self, job_id: str) -> Job | None:
        return self._session.get(Job, job_id)

    def _require(self, job_id: str) -> Job:
        job = self.get_by_id(job_id)
        if job is None:
            raise NotFoundError("Job não encontrado.")
        return job

    def list_for_video(self, video_id: str, *, status: JobStatus | None = None) -> Sequence[Job]:
        stmt = select(Job).where(Job.video_id == video_id).order_by(Job.created_at, Job.id)
        if status is not None:
            stmt = stmt.where(Job.status == status)
        return self._session.execute(stmt).scalars().all()

    def list_by_status(self, status: JobStatus, *, limit: int = 100) -> Sequence[Job]:
        stmt = select(Job).where(Job.status == status).order_by(Job.created_at, Job.id).limit(limit)
        return self._session.execute(stmt).scalars().all()

    def reset_to_queued(self, job_id: str) -> Job:
        """Devolve um job à fila sem consumir tentativa."""
        job = self._require(job_id)
        job.status = JobStatus.QUEUED
        job.started_at = None
        job.finished_at = None
        self._session.flush()
        return job

    def claim(self, job_id: str) -> bool:
        """Assume o job para execução, de forma atômica.

        UPDATE condicional a `status = 'queued'`: o banco decide o vencedor, e
        `rowcount` diz se fomos nós. Só quem recebe `True` pode executar o
        handler — e a tentativa é consumida exatamente aqui, uma única vez.

        SQL portátil entre SQLite e PostgreSQL.
        """
        now = utcnow()
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.QUEUED)
            .values(
                status=JobStatus.RUNNING,
                attempt=Job.attempt + 1,
                started_at=now,
                finished_at=None,
                error_code=None,
                error_message=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        # `Session.execute` é tipado genericamente; um UPDATE sempre devolve
        # CursorResult, que é quem expõe rowcount.
        result = cast(CursorResult[Any], self._session.execute(stmt))
        claimed = result.rowcount == 1

        if claimed:
            # O UPDATE não passa pelo ORM: sem isto, uma instância já carregada
            # na sessão continuaria com os valores antigos.
            tracked = self._session.get(Job, job_id)
            if tracked is not None:
                self._session.refresh(tracked)

        return claimed

    def update_progress(
        self, job_id: str, progress: int, *, current_stage: str | None = None
    ) -> Job:
        job = self._require(job_id)
        job.progress = progress
        if current_stage is not None:
            job.current_stage = current_stage
        self._session.flush()
        return job

    def mark_succeeded(self, job_id: str) -> Job:
        job = self._require(job_id)
        job.status = JobStatus.SUCCEEDED
        job.progress = 100
        job.finished_at = utcnow()
        self._session.flush()
        return job

    def mark_failed(self, job_id: str, error_code: str, error_message: str) -> Job:
        job = self._require(job_id)
        job.status = JobStatus.FAILED
        job.error_code = error_code
        job.error_message = error_message
        job.finished_at = utcnow()
        self._session.flush()
        return job

    def can_retry(self, job: Job) -> bool:
        return job.status == JobStatus.FAILED and job.attempt < job.max_attempts

    def can_retry_after_interruption(self, job: Job) -> bool:
        """Job que ficou `running` após crash: a tentativa já foi consumida."""
        return job.attempt < job.max_attempts
