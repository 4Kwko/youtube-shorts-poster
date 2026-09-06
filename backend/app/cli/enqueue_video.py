"""Cria um Video e um Job de ingestão sem passar por HTTP.

    python -m app.cli.enqueue_video "https://..."

O job fica `queued` no banco; o worker o descobre na varredura, então os dois
processos não precisam compartilhar a fila em memória.
"""

from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.models.enums import JobType, VideoStatus
from app.repositories import JobRepository, VideoRepository
from app.services.ingest.urls import validate_video_url

EXIT_OK = 0
EXIT_INVALID_INPUT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.enqueue_video",
        description="Registra um vídeo e enfileira o job de ingestão.",
    )
    parser.add_argument("url", help="URL http(s) de um provedor suportado.")
    parser.add_argument("--log-level", default="WARNING", help="Nível de log (padrão: WARNING).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    settings = get_settings()
    configure_logging(settings.model_copy(update={"log_level": args.log_level.upper()}))

    try:
        # Falha cedo em URL inválida: melhor recusar aqui do que criar um job
        # que só vai falhar no worker.
        validated = validate_video_url(args.url)
    except AppError as exc:
        print(f"Erro [{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    engine = create_db_engine(settings)
    try:
        with session_scope(create_session_factory(engine)) as session:
            video = VideoRepository(session).create(
                source_url=validated.url,
                provider=validated.provider.name,
                status=VideoStatus.QUEUED,
            )
            job = JobRepository(session).create(video_id=video.id, job_type=JobType.INGEST)
            video_id, job_id = video.id, job.id
    finally:
        engine.dispose()

    print(f"Video: {video_id}")
    print(f"Job:   {job_id} ({JobType.INGEST.value}, queued)")
    print("Rode `python -m app.worker` para processar.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
