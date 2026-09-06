"""Testes da camada de persistência.

Cada teste roda contra um SQLite de arquivo próprio, criado pelas migrations
do Alembic — assim a migration é exercitada junto com o modelo, e um desvio
entre os dois quebra a suíte.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.models.enums import ClipStatus, JobStatus, JobType, VideoStatus
from app.models.video import Video
from app.repositories import (
    ClipRepository,
    JobRepository,
    VideoMetadata,
    VideoRepository,
    video_metadata_from_source,
)
from app.schemas.ingest import VideoSourceInfo

SOURCE_URL = "https://www.youtube.com/watch?v=abc123"


def _run_migrations(database_url: str, project_root: Path) -> None:
    from alembic.config import Config

    from alembic import command

    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def db_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'test.db'}"})


@pytest.fixture
def engine(db_settings: Settings, project_root: Path) -> Iterator[Engine]:
    _run_migrations(db_settings.database_url, project_root)
    engine = create_db_engine(db_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Sessão sem commit: os testes de constraint terminam com a transação suja."""
    active = session_factory()
    try:
        yield active
    finally:
        active.rollback()
        active.close()


@pytest.fixture
def video(session: Session) -> Video:
    return VideoRepository(session).create(source_url=SOURCE_URL, provider="youtube")


# --- migration ------------------------------------------------------------


def test_migration_creates_expected_schema(engine: Engine) -> None:
    inspector = inspect(engine)

    assert {"videos", "jobs", "clips"} <= set(inspector.get_table_names())
    assert {index["name"] for index in inspector.get_indexes("videos")} >= {
        "ix_videos_status",
        "ix_videos_created_at",
    }
    assert {index["name"] for index in inspector.get_indexes("jobs")} >= {
        "ix_jobs_video_id",
        "ix_jobs_status",
    }
    assert "ix_clips_video_id" in {index["name"] for index in inspector.get_indexes("clips")}


# --- CRUD e timestamps ----------------------------------------------------


def test_create_video_defaults(video: Video) -> None:
    assert video.status is VideoStatus.PENDING
    assert video.progress == 0
    assert len(video.id) == 32
    assert video.created_at.tzinfo is not None
    assert video.created_at.astimezone(UTC) == video.created_at.astimezone(UTC)


def test_get_by_id_and_missing(session: Session, video: Video) -> None:
    repo = VideoRepository(session)

    assert repo.get_by_id(video.id) is not None
    assert repo.get_by_id("inexistente") is None


def test_update_status_and_progress(session: Session, video: Video) -> None:
    updated = VideoRepository(session).update_status(
        video.id, VideoStatus.DOWNLOADING, progress=42, current_stage="download"
    )

    assert updated.status is VideoStatus.DOWNLOADING
    assert updated.progress == 42
    assert updated.current_stage == "download"


def test_update_metadata_only_overwrites_provided_fields(session: Session, video: Video) -> None:
    repo = VideoRepository(session)
    repo.update_metadata(video.id, VideoMetadata(title="Título", width=1920, height=1080))
    repo.update_metadata(video.id, VideoMetadata(fps=30.0))

    refreshed = repo.get_by_id(video.id)
    assert refreshed is not None
    assert refreshed.title == "Título"
    assert refreshed.width == 1920
    assert refreshed.fps == 30.0


def test_mark_failed_records_error(session: Session, video: Video) -> None:
    failed = VideoRepository(session).mark_failed(video.id, "video_unavailable", "indisponível")

    assert failed.status is VideoStatus.FAILED
    assert failed.error_code == "video_unavailable"


def test_repository_raises_for_missing_video(session: Session) -> None:
    with pytest.raises(NotFoundError):
        VideoRepository(session).update_status("nao-existe", VideoStatus.QUEUED)


def test_list_filters_by_status_and_paginates(session: Session) -> None:
    repo = VideoRepository(session)
    for _ in range(3):
        repo.create(source_url=SOURCE_URL, provider="youtube", status=VideoStatus.COMPLETED)
    repo.create(source_url=SOURCE_URL, provider="youtube", status=VideoStatus.FAILED)

    assert len(repo.list(status=VideoStatus.COMPLETED)) == 3
    assert len(repo.list(status=VideoStatus.FAILED)) == 1
    assert len(repo.list(limit=2)) == 2
    assert len(repo.list(limit=2, offset=3)) == 1


# --- relacionamentos ------------------------------------------------------


def test_video_relationships(session: Session, video: Video) -> None:
    JobRepository(session).create(video_id=video.id, job_type=JobType.INGEST)
    ClipRepository(session).create(video_id=video.id, sequence=0, start_time=0, end_time=10)
    session.flush()

    assert len(video.jobs) == 1
    assert len(video.clips) == 1
    assert video.jobs[0].video is video


def test_delete_video_cascades(session: Session, video: Video) -> None:
    job = JobRepository(session).create(video_id=video.id, job_type=JobType.INGEST)
    clip = ClipRepository(session).create(video_id=video.id, sequence=0, start_time=0, end_time=5)
    job_id, clip_id = job.id, clip.id

    session.delete(video)
    session.flush()
    session.expunge_all()

    assert JobRepository(session).get_by_id(job_id) is None
    assert ClipRepository(session).get_by_id(clip_id) is None


def test_job_requires_existing_video(session: Session) -> None:
    with pytest.raises(IntegrityError):
        JobRepository(session).create(video_id="fantasma", job_type=JobType.INGEST)


# --- ciclo de vida do job -------------------------------------------------


def test_job_lifecycle(session: Session, video: Video) -> None:
    repo = JobRepository(session)
    job = repo.create(video_id=video.id, job_type=JobType.INGEST)
    assert (job.status, job.attempt) == (JobStatus.QUEUED, 0)

    assert repo.claim(job.id) is True
    running = repo.get_by_id(job.id)
    assert running is not None
    assert (running.status, running.attempt) == (JobStatus.RUNNING, 1)
    assert running.started_at is not None

    in_progress = repo.update_progress(job.id, 55, current_stage="download")
    assert (in_progress.progress, in_progress.current_stage) == (55, "download")

    done = repo.mark_succeeded(job.id)
    assert (done.status, done.progress) == (JobStatus.SUCCEEDED, 100)
    assert done.finished_at is not None


def test_claim_clears_previous_error_and_counts_attempts(session: Session, video: Video) -> None:
    repo = JobRepository(session)
    job = repo.create(video_id=video.id, job_type=JobType.INGEST)

    repo.claim(job.id)
    repo.mark_failed(job.id, "video_download_failed", "timeout")
    assert repo.can_retry(job) is True

    repo.reset_to_queued(job.id)
    assert repo.claim(job.id) is True
    assert job.attempt == 2
    assert job.error_code is None
    assert job.finished_at is None


def test_can_retry_respects_max_attempts(session: Session, video: Video) -> None:
    repo = JobRepository(session)
    job = repo.create(video_id=video.id, job_type=JobType.INGEST, max_attempts=1)
    repo.claim(job.id)
    repo.mark_failed(job.id, "erro", "falhou")

    assert repo.can_retry(job) is False


def test_list_jobs_for_video(session: Session, video: Video) -> None:
    repo = JobRepository(session)
    repo.create(video_id=video.id, job_type=JobType.INGEST)
    repo.create(video_id=video.id, job_type=JobType.TRANSCRIBE)
    other = VideoRepository(session).create(source_url=SOURCE_URL, provider="youtube")
    repo.create(video_id=other.id, job_type=JobType.RENDER)

    assert len(repo.list_for_video(video.id)) == 2


# --- constraints ----------------------------------------------------------


@pytest.mark.parametrize("progress", [-1, 101])
def test_video_progress_range_is_enforced(session: Session, video: Video, progress: int) -> None:
    video.progress = progress

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("progress", [-5, 200])
def test_job_progress_range_is_enforced(session: Session, video: Video, progress: int) -> None:
    job = JobRepository(session).create(video_id=video.id, job_type=JobType.CLIP)
    job.progress = progress

    with pytest.raises(IntegrityError):
        session.flush()


def test_clip_start_time_cannot_be_negative(session: Session, video: Video) -> None:
    with pytest.raises(IntegrityError):
        ClipRepository(session).create(video_id=video.id, sequence=0, start_time=-1, end_time=5)


def test_clip_end_must_be_after_start(session: Session, video: Video) -> None:
    with pytest.raises(IntegrityError):
        ClipRepository(session).create(video_id=video.id, sequence=0, start_time=10, end_time=10)


def test_clip_sequence_cannot_be_negative(session: Session, video: Video) -> None:
    with pytest.raises(IntegrityError):
        ClipRepository(session).create(video_id=video.id, sequence=-1, start_time=0, end_time=5)


def test_clip_sequence_is_unique_per_video(session: Session, video: Video) -> None:
    repo = ClipRepository(session)
    repo.create(video_id=video.id, sequence=0, start_time=0, end_time=5)

    with pytest.raises(IntegrityError):
        repo.create(video_id=video.id, sequence=0, start_time=5, end_time=9)


def test_same_sequence_allowed_across_videos(session: Session, video: Video) -> None:
    other = VideoRepository(session).create(source_url=SOURCE_URL, provider="youtube")
    repo = ClipRepository(session)

    repo.create(video_id=video.id, sequence=0, start_time=0, end_time=5)
    repo.create(video_id=other.id, sequence=0, start_time=0, end_time=5)
    session.flush()

    assert len(repo.list_for_video(video.id)) == 1


def test_clip_duration_is_derived_and_ordered(session: Session, video: Video) -> None:
    repo = ClipRepository(session)
    repo.create(video_id=video.id, sequence=1, start_time=10, end_time=25)
    repo.create(video_id=video.id, sequence=0, start_time=0, end_time=10)
    session.flush()

    clips = repo.list_for_video(video.id)
    assert [clip.sequence for clip in clips] == [0, 1]
    assert clips[1].duration == 15
    assert clips[0].status is ClipStatus.PENDING


# --- transação ------------------------------------------------------------


def test_session_scope_commits(session_factory: sessionmaker[Session]) -> None:
    with session_scope(session_factory) as active:
        created = VideoRepository(active).create(source_url=SOURCE_URL, provider="youtube")
        video_id = created.id

    with session_scope(session_factory) as active:
        assert VideoRepository(active).get_by_id(video_id) is not None


def test_session_scope_rolls_back_on_error(session_factory: sessionmaker[Session]) -> None:
    video_id: str | None = None

    with pytest.raises(RuntimeError), session_scope(session_factory) as active:
        created = VideoRepository(active).create(source_url=SOURCE_URL, provider="youtube")
        video_id = created.id
        raise RuntimeError("falha no meio da unidade de trabalho")

    assert video_id is not None
    with session_scope(session_factory) as active:
        assert VideoRepository(active).get_by_id(video_id) is None


def test_constraint_violation_rolls_back_whole_unit(
    session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError), session_scope(session_factory) as active:
        repo = VideoRepository(active)
        repo.create(source_url=SOURCE_URL, provider="youtube")
        bad = repo.create(source_url=SOURCE_URL, provider="youtube")
        bad.progress = 500

    with session_scope(session_factory) as active:
        assert VideoRepository(active).list() == []


# --- mapper ---------------------------------------------------------------


def test_video_metadata_from_source_info() -> None:
    info = VideoSourceInfo(
        id="a" * 32,
        source_url=SOURCE_URL,
        provider="youtube",
        provider_video_id="abc123",
        title="Exemplo",
        duration_seconds=120.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        container="mov,mp4",
        file_size_bytes=1024,
        local_filename="source.mp4",
    )

    metadata = video_metadata_from_source(info)

    assert metadata.duration == 120.0
    assert metadata.file_size == 1024
    assert metadata.source_file_key == f"{'a' * 32}/source.mp4"
    assert not metadata.source_file_key.startswith("/")


def test_mapper_applied_to_video(session: Session, video: Video) -> None:
    info = VideoSourceInfo(
        id=video.id,
        source_url=SOURCE_URL,
        provider="youtube",
        local_filename="source.mkv",
        file_size_bytes=99,
    )

    updated = VideoRepository(session).update_metadata(video.id, video_metadata_from_source(info))

    assert updated.source_file_key == f"{video.id}/source.mkv"
    assert updated.file_size == 99
    assert updated.title is None


# --- claim atômico --------------------------------------------------------


def test_claim_succeeds_once_and_consumes_one_attempt(session: Session, video: Video) -> None:
    repo = JobRepository(session)
    job = repo.create(video_id=video.id, job_type=JobType.INGEST)

    assert repo.claim(job.id) is True
    # Segundo claim do mesmo job: o UPDATE não encontra `queued` e não altera nada.
    assert repo.claim(job.id) is False
    assert job.attempt == 1
    assert job.status is JobStatus.RUNNING


@pytest.mark.parametrize(
    "status",
    [JobStatus.RUNNING, JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED],
)
def test_claim_requires_queued_status(session: Session, video: Video, status: JobStatus) -> None:
    repo = JobRepository(session)
    job = repo.create(video_id=video.id, job_type=JobType.INGEST)
    job.status = status
    session.flush()

    assert repo.claim(job.id) is False
    assert job.attempt == 0


def test_claim_of_unknown_job_is_false_not_error(session: Session) -> None:
    assert JobRepository(session).claim("nao-existe") is False


def test_claim_after_requeue_increments_again(session: Session, video: Video) -> None:
    repo = JobRepository(session)
    job = repo.create(video_id=video.id, job_type=JobType.INGEST, max_attempts=3)

    repo.claim(job.id)
    repo.mark_failed(job.id, "video_download_failed", "timeout")
    repo.reset_to_queued(job.id)

    assert repo.claim(job.id) is True
    assert job.attempt == 2
    assert job.error_code is None
    assert job.finished_at is None
