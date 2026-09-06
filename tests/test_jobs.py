"""Testes do worker e da fila.

A ingestão real é sempre substituída: nenhum teste toca rede ou yt-dlp.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.jobs import handlers as handlers_module
from app.jobs.context import JobContext
from app.jobs.handlers import UnknownJobTypeError, get_handler
from app.jobs.queue import InMemoryJobQueue
from app.jobs.worker import ORPHAN_ERROR_CODE, Worker
from app.models.enums import JobStatus, JobType, VideoStatus
from app.repositories import JobRepository, VideoRepository
from app.schemas.ingest import VideoSourceInfo
from app.services.ingest.errors import VideoUnavailableError
from app.services.ingest.progress import IngestStage

SOURCE_URL = "https://www.youtube.com/watch?v=abc123"


def _run_migrations(database_url: str, project_root: Path) -> None:
    from alembic.config import Config

    from alembic import command

    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture
def db_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'jobs.db'}"})


@pytest.fixture
def engine(db_settings: Settings) -> Iterator[Engine]:
    _run_migrations(db_settings.database_url, Path(__file__).resolve().parents[1])
    engine = create_db_engine(db_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def worker(
    db_settings: Settings, session_factory: sessionmaker[Session], queue: InMemoryJobQueue
) -> Worker:
    return Worker(db_settings, session_factory, queue)


def _create_job(
    session_factory: sessionmaker[Session], *, max_attempts: int = 3
) -> tuple[str, str]:
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url=SOURCE_URL, provider="youtube", status=VideoStatus.QUEUED
        )
        job = JobRepository(session).create(
            video_id=video.id, job_type=JobType.INGEST, max_attempts=max_attempts
        )
        return video.id, job.id


def _job(session_factory: sessionmaker[Session], job_id: str) -> Any:
    with session_scope(session_factory) as session:
        job = JobRepository(session).get_by_id(job_id)
        assert job is not None
        session.expunge(job)
        return job


def _video(session_factory: sessionmaker[Session], video_id: str) -> Any:
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(video_id)
        assert video is not None
        session.expunge(video)
        return video


def _fake_import(video_id: str = "f" * 32, **overrides: Any) -> Any:
    info = VideoSourceInfo(
        id=video_id,
        source_url=SOURCE_URL,
        provider="youtube",
        provider_video_id="abc123",
        title="Vídeo de teste",
        duration_seconds=90.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        container="mov,mp4",
        file_size_bytes=4_000_000_000,
        local_filename="source.mp4",
        **overrides,
    )

    def _import(settings: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        on_progress = kwargs.get("on_progress")
        if on_progress is not None:
            on_progress(IngestStage.DOWNLOADING, 10)
        return info

    return _import


# --- fila -----------------------------------------------------------------


def test_queue_fifo_and_dedupe(queue: InMemoryJobQueue) -> None:
    queue.enqueue("a")
    queue.enqueue("b")
    queue.enqueue("a")

    assert len(queue) == 2
    assert queue.get_next() == "a"
    assert queue.get_next() == "b"
    assert queue.get_next() is None


def test_queue_does_not_redeliver_in_flight_job(queue: InMemoryJobQueue) -> None:
    queue.enqueue("a")
    queue.get_next()
    queue.enqueue("a")

    assert queue.get_next() is None

    queue.acknowledge("a")
    queue.enqueue("a")
    assert queue.get_next() == "a"


def test_queue_fail_requeues_only_when_asked(queue: InMemoryJobQueue) -> None:
    queue.enqueue("a")
    queue.get_next()
    queue.fail("a", requeue=False)
    assert queue.get_next() is None

    queue.enqueue("a")
    queue.get_next()
    queue.fail("a", requeue=True)
    assert queue.get_next() == "a"


# --- dispatch -------------------------------------------------------------


def test_only_implemented_handlers_are_registered() -> None:
    assert get_handler(JobType.INGEST) is not None
    assert get_handler(JobType.CLIP) is not None
    assert get_handler(JobType.RENDER) is not None
    assert get_handler(JobType.TRANSCRIBE) is not None

    for job_type in (JobType.FULL_PIPELINE,):
        with pytest.raises(UnknownJobTypeError):
            get_handler(job_type)


def test_handlers_do_not_import_yt_dlp() -> None:
    """A dependência do yt-dlp fica na camada de ingestão, não no worker."""
    source = Path(handlers_module.__file__).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]

    assert not any("yt_dlp" in line for line in imports)


def test_unknown_job_type_fails_job_without_side_effects(
    session_factory: sessionmaker[Session], worker: Worker, queue: InMemoryJobQueue
) -> None:
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(source_url=SOURCE_URL, provider="youtube")
        job = JobRepository(session).create(video_id=video.id, job_type=JobType.FULL_PIPELINE)
        video_id, job_id = video.id, job.id

    queue.enqueue(job_id)
    worker.process_one()

    assert _job(session_factory, job_id).status is JobStatus.FAILED
    assert _job(session_factory, job_id).error_code == "unknown_job_type"
    assert _video(session_factory, video_id).status is VideoStatus.FAILED


# --- execução bem sucedida ------------------------------------------------


def test_worker_runs_ingest_job(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory)
    monkeypatch.setattr(handlers_module, "import_video", _fake_import())

    queue.enqueue(job_id)
    assert worker.process_one() is True

    job = _job(session_factory, job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert job.attempt == 1
    assert job.progress == 100
    assert job.started_at is not None and job.finished_at is not None

    video = _video(session_factory, video_id)
    assert video.status is VideoStatus.DOWNLOADED
    assert video.progress == 100
    assert video.error_code is None


def test_metadata_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory)
    monkeypatch.setattr(handlers_module, "import_video", _fake_import(video_id="e" * 32))

    queue.enqueue(job_id)
    worker.process_one()

    video = _video(session_factory, video_id)
    assert video.title == "Vídeo de teste"
    assert (video.width, video.height, video.fps) == (1920, 1080, 30.0)
    assert (video.video_codec, video.audio_codec) == ("h264", "aac")
    assert video.duration == 90.0
    assert video.provider_video_id == "abc123"
    assert video.source_file_key == f"{'e' * 32}/source.mp4"
    # BigInteger: acima do limite de 32 bits com sinal.
    assert video.file_size == 4_000_000_000


def test_progress_is_visible_before_job_finishes(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory)
    seen: list[int] = []

    def _import(settings: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        kwargs["on_progress"](IngestStage.DOWNLOADING, 10)
        # Transação própria por atualização: o progresso já está commitado aqui.
        seen.append(_video(session_factory, video_id).progress)
        result: VideoSourceInfo = _fake_import()(settings, url)
        return result

    monkeypatch.setattr(handlers_module, "import_video", _import)
    queue.enqueue(job_id)
    worker.process_one()

    assert seen == [10]


# --- falhas ---------------------------------------------------------------


def test_ingest_failure_marks_job_and_video_failed(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory, max_attempts=1)

    def _boom(settings: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        raise VideoUnavailableError("O vídeo não está disponível para download.")

    monkeypatch.setattr(handlers_module, "import_video", _boom)
    queue.enqueue(job_id)
    worker.process_one()

    job = _job(session_factory, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error_code == "video_unavailable"
    assert job.finished_at is not None

    video = _video(session_factory, video_id)
    assert video.status is VideoStatus.FAILED
    assert video.error_code == "video_unavailable"


def test_unexpected_exception_does_not_leak_details(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory, max_attempts=1)

    def _boom(settings: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        raise RuntimeError("/srv/interno/segredo.mp4 explodiu")

    monkeypatch.setattr(handlers_module, "import_video", _boom)
    queue.enqueue(job_id)
    worker.process_one()

    job = _job(session_factory, job_id)
    assert job.error_code == "internal_error"
    assert "segredo" not in (job.error_message or "")
    assert _video(session_factory, video_id).status is VideoStatus.FAILED


def test_failure_never_leaves_job_running(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    _, job_id = _create_job(session_factory, max_attempts=1)
    monkeypatch.setattr(
        handlers_module,
        "import_video",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falhou")),
    )

    queue.enqueue(job_id)
    worker.process_one()

    assert _job(session_factory, job_id).status is not JobStatus.RUNNING


# --- retry ----------------------------------------------------------------


def test_permanent_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    """Vídeo indisponível falharia igual na segunda tentativa."""
    _, job_id = _create_job(session_factory, max_attempts=3)

    def _boom(settings: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        raise VideoUnavailableError("O vídeo não está disponível para download.")

    monkeypatch.setattr(handlers_module, "import_video", _boom)
    queue.enqueue(job_id)
    worker.process_one()

    assert _job(session_factory, job_id).status is JobStatus.FAILED
    assert len(queue) == 0


def test_failed_job_is_requeued_until_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory, max_attempts=2)
    monkeypatch.setattr(
        handlers_module,
        "import_video",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falhou")),
    )

    queue.enqueue(job_id)
    worker.process_one()

    assert _job(session_factory, job_id).attempt == 1
    assert len(queue) == 1
    # Enquanto houver tentativa, o vídeo volta para a fila em vez de falhar.
    assert _video(session_factory, video_id).status is VideoStatus.QUEUED

    worker.process_one()
    job = _job(session_factory, job_id)
    assert job.attempt == 2
    assert job.status is JobStatus.FAILED
    assert _video(session_factory, video_id).status is VideoStatus.FAILED
    # Esgotadas as tentativas, o job sai da fila e não volta.
    assert len(queue) == 0
    assert worker.process_one() is False


# --- recuperação ----------------------------------------------------------


def test_recover_enqueues_queued_jobs(
    session_factory: sessionmaker[Session], worker: Worker, queue: InMemoryJobQueue
) -> None:
    _, job_id = _create_job(session_factory)

    assert worker.recover() == 1
    assert queue.get_next() == job_id


def test_recover_returns_orphan_running_job_to_queue(
    session_factory: sessionmaker[Session], worker: Worker, queue: InMemoryJobQueue
) -> None:
    _, job_id = _create_job(session_factory, max_attempts=3)
    with session_scope(session_factory) as session:
        JobRepository(session).claim(job_id)

    worker.recover()

    job = _job(session_factory, job_id)
    assert job.status is JobStatus.QUEUED
    assert job.started_at is None
    assert queue.get_next() == job_id


def test_recover_fails_orphan_without_attempts_left(
    session_factory: sessionmaker[Session], worker: Worker, queue: InMemoryJobQueue
) -> None:
    video_id, job_id = _create_job(session_factory, max_attempts=1)
    with session_scope(session_factory) as session:
        JobRepository(session).claim(job_id)

    worker.recover()

    assert _job(session_factory, job_id).error_code == ORPHAN_ERROR_CODE
    assert _job(session_factory, job_id).status is JobStatus.FAILED
    assert _video(session_factory, video_id).status is VideoStatus.FAILED
    assert len(queue) == 0


def test_recover_is_idempotent(
    session_factory: sessionmaker[Session], worker: Worker, queue: InMemoryJobQueue
) -> None:
    _create_job(session_factory)

    worker.recover()
    worker.recover()

    assert len(queue) == 1


def test_terminal_job_in_queue_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    _, job_id = _create_job(session_factory)
    with session_scope(session_factory) as session:
        JobRepository(session).mark_succeeded(job_id)

    called = False

    def _import(*args: Any, **kwargs: Any) -> VideoSourceInfo:
        nonlocal called
        called = True
        raise AssertionError("handler não deveria rodar")

    monkeypatch.setattr(handlers_module, "import_video", _import)
    queue.enqueue(job_id)
    worker.process_one()

    assert called is False
    assert _job(session_factory, job_id).status is JobStatus.SUCCEEDED


# --- claim atômico no worker ---------------------------------------------


def test_second_worker_does_not_run_claimed_job(
    monkeypatch: pytest.MonkeyPatch,
    db_settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    """Dois workers com o mesmo job na fila: só um executa o handler."""
    _, job_id = _create_job(session_factory)
    calls: list[str] = []

    def _import(settings: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        calls.append(url)
        result: VideoSourceInfo = _fake_import()(settings, url)
        return result

    monkeypatch.setattr(handlers_module, "import_video", _import)

    queue_a, queue_b = InMemoryJobQueue(), InMemoryJobQueue()
    worker_a = Worker(db_settings, session_factory, queue_a)
    worker_b = Worker(db_settings, session_factory, queue_b)
    queue_a.enqueue(job_id)
    queue_b.enqueue(job_id)

    worker_a.process_one()
    worker_b.process_one()

    assert len(calls) == 1
    job = _job(session_factory, job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert job.attempt == 1


def test_worker_skips_job_already_running(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    _, job_id = _create_job(session_factory)
    with session_scope(session_factory) as session:
        JobRepository(session).claim(job_id)

    monkeypatch.setattr(
        handlers_module,
        "import_video",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("handler não deveria rodar")),
    )
    queue.enqueue(job_id)
    worker.process_one()

    job = _job(session_factory, job_id)
    assert job.status is JobStatus.RUNNING
    assert job.attempt == 1


# --- encadeamento ingest -> clip -----------------------------------------


def test_successful_ingest_enqueues_exactly_one_transcribe_job(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory)
    monkeypatch.setattr(handlers_module, "import_video", _fake_import())

    queue.enqueue(job_id)
    worker.process_one()

    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_for_video(video_id)
        next_jobs = [job for job in jobs if job.job_type is JobType.TRANSCRIBE]

        assert len(next_jobs) == 1
        assert next_jobs[0].status is JobStatus.QUEUED
        assert next_jobs[0].attempt == 0


def test_repeated_ingest_does_not_duplicate_next_job(
    monkeypatch: pytest.MonkeyPatch,
    db_settings: Settings,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    """Reexecução da ingestão não pode virar cadeia de jobs."""
    video_id, job_id = _create_job(session_factory)
    monkeypatch.setattr(handlers_module, "import_video", _fake_import())

    queue.enqueue(job_id)
    worker.process_one()

    context = JobContext(
        settings=db_settings,
        session_factory=session_factory,
        job_id=job_id,
        video_id=video_id,
        job_type=JobType.INGEST,
    )
    handlers_module.handle_ingest(context)
    handlers_module.handle_ingest(context)

    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_for_video(video_id)
        assert len([job for job in jobs if job.job_type is JobType.TRANSCRIBE]) == 1


def test_failed_ingest_does_not_enqueue_next_job(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    video_id, job_id = _create_job(session_factory, max_attempts=1)

    def _boom(settings: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        raise VideoUnavailableError("indisponível")

    monkeypatch.setattr(handlers_module, "import_video", _boom)
    queue.enqueue(job_id)
    worker.process_one()

    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_for_video(video_id)
        assert not [job for job in jobs if job.job_type is JobType.TRANSCRIBE]


def test_worker_picks_up_chained_job(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    worker: Worker,
    queue: InMemoryJobQueue,
) -> None:
    """Cadeia: ingest roda, transcribe é enfileirado e processado a seguir."""
    video_id, job_id = _create_job(session_factory)
    monkeypatch.setattr(handlers_module, "import_video", _fake_import())

    transcribed: list[str] = []

    def _fake_transcribe(context: JobContext) -> None:
        transcribed.append(context.video_id)
        with session_scope(session_factory) as session:
            VideoRepository(session).update_status(
                context.video_id,
                VideoStatus.TRANSCRIBED,
                progress=100,
                current_stage="transcribed",
            )

    monkeypatch.setitem(handlers_module.HANDLERS, JobType.TRANSCRIBE, _fake_transcribe)

    queue.enqueue(job_id)
    worker.process_one()
    # Fila vazia: o worker descobre o job novo varrendo o banco.
    worker.recover()
    assert worker.process_one() is True

    assert transcribed == [video_id]
    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_for_video(video_id)
        video = VideoRepository(session).get_by_id(video_id)

        assert [job.status for job in jobs] == [JobStatus.SUCCEEDED, JobStatus.SUCCEEDED]
        assert video is not None
        assert video.status is VideoStatus.TRANSCRIBED
