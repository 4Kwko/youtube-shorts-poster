"""Worker local.

Processamento sequencial, um job por vez, em um único processo. A estrutura
já separa fila, dispatch e execução, então rodar vários workers depois é
trocar a fila e adicionar um claim atômico no banco — nada aqui muda de forma.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import session_scope
from app.jobs.context import JobContext
from app.jobs.handlers import UnknownJobTypeError, get_handler
from app.jobs.queue import JobQueue
from app.models.enums import JobStatus, VideoStatus
from app.repositories import JobRepository, VideoRepository

logger = logging.getLogger(__name__)

ORPHAN_ERROR_CODE = "worker_interrupted"


def _is_retryable(exc: Exception) -> bool:
    """Só reenfileira o que pode dar certo numa segunda tentativa.

    Erro permanente (vídeo indisponível, longo demais, tipo de job sem handler)
    falharia de novo de forma idêntica; gastar tentativa nele só atrasa o
    diagnóstico. Falha técnica (rede, timeout, erro interno) é retentável.
    """
    if isinstance(exc, UnknownJobTypeError):
        return False
    if isinstance(exc, AppError):
        return exc.status_code >= 500
    return True


class Worker:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        queue: JobQueue,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._queue = queue

    # --- recuperação ------------------------------------------------------

    def recover(self) -> int:
        """Reconstrói a fila a partir do banco.

        Política para jobs órfãos em `running`: como há um único worker, um job
        nesse estado na inicialização só pode ter sobrado de um crash. Ele volta
        para `queued` se ainda houver tentativa disponível; caso contrário é
        encerrado como `failed`, junto com o Video, para não ficar preso.
        """
        with session_scope(self._session_factory) as session:
            jobs = JobRepository(session)
            videos = VideoRepository(session)

            for job in jobs.list_by_status(JobStatus.RUNNING):
                if jobs.can_retry_after_interruption(job):
                    jobs.reset_to_queued(job.id)
                    logger.warning("Job órfão devolvido à fila", extra={"job_id": job.id})
                else:
                    jobs.mark_failed(
                        job.id, ORPHAN_ERROR_CODE, "Worker interrompido durante a execução."
                    )
                    videos.mark_failed(
                        job.video_id, ORPHAN_ERROR_CODE, "Processamento interrompido."
                    )

            queued_ids = [job.id for job in jobs.list_by_status(JobStatus.QUEUED)]

        for job_id in queued_ids:
            self._queue.enqueue(job_id)

        if queued_ids:
            logger.info("Jobs recuperados do banco", extra={"count": len(queued_ids)})
        return len(queued_ids)

    # --- execução ---------------------------------------------------------

    def _start_job(self, job_id: str) -> JobContext | None:
        """Tenta assumir o job. Retorna o contexto apenas se o claim foi nosso.

        Transação curta: termina antes do handler começar, para não segurar
        conexão durante o download.
        """
        with session_scope(self._session_factory) as session:
            jobs = JobRepository(session)
            job = jobs.get_by_id(job_id)
            if job is None:
                logger.warning("Job da fila não existe mais", extra={"job_id": job_id})
                return None
            video_id, job_type = job.video_id, job.job_type

            if not jobs.claim(job_id):
                # Outro worker assumiu, ou o job já saiu de `queued`. Não é erro:
                # simplesmente não é nosso.
                logger.info("Job não assumido", extra={"job_id": job_id})
                return None

            jobs.update_progress(job_id, 0, current_stage="starting")
            VideoRepository(session).update_status(
                video_id, VideoStatus.DOWNLOADING, progress=0, current_stage="starting"
            )
            return JobContext(
                settings=self._settings,
                session_factory=self._session_factory,
                job_id=job_id,
                video_id=video_id,
                job_type=job_type,
            )

    def _finish_success(self, context: JobContext) -> None:
        with session_scope(self._session_factory) as session:
            JobRepository(session).mark_succeeded(context.job_id)

    def _finish_failure(self, context: JobContext, exc: Exception) -> bool:
        """Registra a falha e informa se o job ainda pode ser retentado.

        O Video só vai para `failed` quando não há mais tentativa: marcar o
        vídeo como falho enquanto o job ainda será retentado deixaria os dois
        estados contraditórios no banco.
        """
        if isinstance(exc, AppError):
            error_code, message = exc.code, exc.message
        else:
            error_code, message = "internal_error", "Falha inesperada no processamento."

        logger.exception(
            "Job falhou",
            extra={
                "job_id": context.job_id,
                "video_id": context.video_id,
                "error_code": error_code,
            },
        )

        with session_scope(self._session_factory) as session:
            jobs = JobRepository(session)
            videos = VideoRepository(session)
            job = jobs.mark_failed(context.job_id, error_code, message)
            will_retry = jobs.can_retry(job) and _is_retryable(exc)

            if will_retry:
                videos.update_status(
                    context.video_id, VideoStatus.QUEUED, progress=0, current_stage="retrying"
                )
            else:
                videos.mark_failed(context.video_id, error_code, message)
            return will_retry

    def process_one(self) -> bool:
        """Processa no máximo um job. Retorna se algo foi processado."""
        job_id = self._queue.get_next()
        if job_id is None:
            return False

        context = self._start_job(job_id)
        if context is None:
            self._queue.acknowledge(job_id)
            return True

        try:
            handler = get_handler(context.job_type)
            handler(context)
        # Handler pode levantar qualquer coisa; a falha é classificada e registrada.
        except Exception as exc:
            retry = self._finish_failure(context, exc)
            # Sem backoff nesta versão: o limite de tentativas é o que impede
            # um job problemático de girar indefinidamente.
            self._queue.fail(job_id, requeue=retry)
            if retry:
                with session_scope(self._session_factory) as session:
                    JobRepository(session).reset_to_queued(job_id)
            return True

        self._finish_success(context)
        self._queue.acknowledge(job_id)
        return True

    def run_forever(self, *, poll_interval: float | None = None) -> None:
        interval = (
            poll_interval if poll_interval is not None else self._settings.worker_poll_seconds
        )
        self.recover()
        logger.info("Worker iniciado")

        while True:
            if self.process_one():
                continue
            # Fila vazia: a fila local não atravessa processos, então varrer o
            # banco é o que permite outro processo (CLI, futura API) enfileirar.
            if self.recover() == 0:
                time.sleep(interval)
