"""Testes da aba Projetos: listagem, miniatura, retry e exclusão."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import session_scope
from app.main import create_app
from app.models.enums import JobStatus, JobType, VideoStatus
from app.repositories import ClipRepository, JobRepository, VideoRepository
from app.schemas.settings import VideoSettings
from app.services.cleanup import VIDEO_SUBDIRS, purge_video_files
from app.services.thumbnails import thumbnail_path

VALID_URL = "https://www.youtube.com/watch?v=abc123"


def _run_migrations(database_url: str) -> None:
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture
def project_settings(settings: Settings, tmp_path: Path) -> Settings:
    database_url = f"sqlite:///{tmp_path / 'projects.db'}"
    _run_migrations(database_url)
    updated = settings.model_copy(update={"database_url": database_url})
    updated.ensure_storage_dirs()
    return updated


@pytest.fixture
def app(project_settings: Settings) -> FastAPI:
    return create_app(project_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(app: FastAPI) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = app.state.session_factory
    return factory


def _make_video(
    session_factory: sessionmaker[Session],
    *,
    status: VideoStatus = VideoStatus.RENDERED,
    clips: int = 0,
    title: str | None = None,
    video_settings: VideoSettings | None = None,
) -> str:
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url=VALID_URL,
            provider="youtube",
            status=status,
            settings=video_settings or VideoSettings(),
        )
        video.title = title
        repository = ClipRepository(session)
        for sequence in range(clips):
            repository.create(
                video_id=video.id,
                sequence=sequence,
                start_time=sequence * 30,
                end_time=sequence * 30 + 30,
            )
        return video.id


# --- listagem -------------------------------------------------------------


def test_list_is_empty_at_first(client: TestClient) -> None:
    body = client.get("/api/v1/videos").json()

    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_returns_newest_first(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    first = _make_video(session_factory, title="antigo")
    # `created_at` tem resolução de microssegundos; o intervalo evita empate.
    time.sleep(0.01)
    second = _make_video(session_factory, title="recente")

    items = client.get("/api/v1/videos").json()["items"]

    assert [item["id"] for item in items] == [second, first]
    assert items[0]["title"] == "recente"


def test_list_paginates(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    for _ in range(5):
        _make_video(session_factory)
        time.sleep(0.005)

    page = client.get("/api/v1/videos?limit=2&offset=2").json()

    assert len(page["items"]) == 2
    assert page["total"] == 5
    assert page["offset"] == 2


def test_clip_count_comes_with_the_summary(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _make_video(session_factory, clips=3)
    time.sleep(0.005)
    _make_video(session_factory, clips=0)

    counts = [item["clip_count"] for item in client.get("/api/v1/videos").json()["items"]]

    assert counts == [0, 3]


def test_list_uses_a_single_query_for_the_page(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sem N+1: a contagem de clips vem agregada, não uma query por vídeo."""
    from sqlalchemy import event

    for _ in range(4):
        _make_video(session_factory, clips=2)

    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = session_factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", record)
    try:
        client.get("/api/v1/videos")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    # Uma para a página, uma para o total.
    assert len(statements) == 2


def test_summary_hides_internal_paths(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    video_id = _make_video(session_factory, clips=1)
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(video_id)
        assert video is not None
        video.source_file_key = f"{video_id}/source.mp4"
        clip = ClipRepository(session).list_for_video(video_id)[0]
        clip.rendered_file_key = f"{video_id}/000.mp4"

    body = client.get("/api/v1/videos").text

    assert "source_file_key" not in body
    assert "rendered_file_key" not in body
    assert "source.mp4" not in body


# --- miniatura ------------------------------------------------------------


def test_thumbnail_missing_returns_404(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    video_id = _make_video(session_factory)

    assert client.get(f"/api/v1/videos/{video_id}/thumbnail").status_code == 404


def test_thumbnail_is_served_when_present(
    client: TestClient, session_factory: sessionmaker[Session], project_settings: Settings
) -> None:
    video_id = _make_video(session_factory)
    path = thumbnail_path(project_settings, video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff jpeg")

    response = client.get(f"/api/v1/videos/{video_id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert str(project_settings.storage_root) not in response.text


def test_thumbnail_of_unknown_video_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/videos/nao-existe/thumbnail").status_code == 404


# --- retry ----------------------------------------------------------------


def _fail_job(session_factory: sessionmaker[Session], video_id: str, job_type: JobType) -> None:
    with session_scope(session_factory) as session:
        jobs = JobRepository(session)
        job = jobs.create(video_id=video_id, job_type=job_type)
        jobs.claim(job.id)
        jobs.mark_failed(job.id, "erro", "falhou")


@pytest.mark.parametrize(
    ("failed", "expected_status"),
    [
        (JobType.EXPORT, "rendered"),
        (JobType.RENDER, "clipped"),
        (JobType.CLIP, "transcribed"),
        (JobType.TRANSCRIBE, "downloaded"),
        (JobType.INGEST, "queued"),
    ],
)
def test_retry_repeats_the_failed_step(
    client: TestClient,
    session_factory: sessionmaker[Session],
    failed: JobType,
    expected_status: str,
) -> None:
    video_id = _make_video(session_factory, status=VideoStatus.FAILED)
    _fail_job(session_factory, video_id, failed)

    body = client.post(f"/api/v1/videos/{video_id}/retry").json()

    assert body["job_type"] == failed.value
    assert body["status"] == expected_status

    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_for_video(video_id)
        queued = [job for job in jobs if job.status is JobStatus.QUEUED]
        assert len(queued) == 1
        assert queued[0].job_type is failed


def test_retry_clears_the_previous_error(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    video_id = _make_video(session_factory, status=VideoStatus.FAILED)
    with session_scope(session_factory) as session:
        VideoRepository(session).mark_failed(video_id, "video_unavailable", "indisponível")
    _fail_job(session_factory, video_id, JobType.INGEST)

    client.post(f"/api/v1/videos/{video_id}/retry")

    body = client.get(f"/api/v1/videos/{video_id}").json()
    assert body["error_code"] is None
    assert body["error_message"] is None


def test_retry_is_refused_while_a_job_is_pending(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    video_id = _make_video(session_factory, status=VideoStatus.PROCESSING)
    with session_scope(session_factory) as session:
        JobRepository(session).create(video_id=video_id, job_type=JobType.RENDER)

    response = client.post(f"/api/v1/videos/{video_id}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_retry_of_unknown_video_returns_404(client: TestClient) -> None:
    assert client.post("/api/v1/videos/nao-existe/retry").status_code == 404


# --- exclusão -------------------------------------------------------------


def _seed_files(settings: Settings, video_id: str) -> None:
    for subdir in VIDEO_SUBDIRS:
        directory = settings.storage_path(subdir) / video_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "arquivo.bin").write_bytes(b"conteudo")


def test_delete_removes_records_and_internal_files(
    client: TestClient,
    session_factory: sessionmaker[Session],
    project_settings: Settings,
) -> None:
    video_id = _make_video(session_factory, clips=2)
    with session_scope(session_factory) as session:
        JobRepository(session).create(video_id=video_id, job_type=JobType.INGEST)
    _seed_files(project_settings, video_id)

    assert client.delete(f"/api/v1/videos/{video_id}").status_code == 204

    with session_scope(session_factory) as session:
        assert VideoRepository(session).get_by_id(video_id) is None
        assert ClipRepository(session).list_for_video(video_id) == []
        assert JobRepository(session).list_for_video(video_id) == []

    for subdir in VIDEO_SUBDIRS:
        assert not (project_settings.storage_path(subdir) / video_id).exists()


def test_delete_keeps_the_exported_files(
    client: TestClient,
    session_factory: sessionmaker[Session],
    project_settings: Settings,
    tmp_path: Path,
) -> None:
    """Excluir o projeto não pode apagar o que o usuário já publicou."""
    export_dir = tmp_path / "Videos" / "Clipper"
    export_dir.mkdir(parents=True)
    exported = export_dir / "clip-001.mp4"
    exported.write_bytes(b"mp4 exportado")

    video_id = _make_video(
        session_factory,
        video_settings=VideoSettings(output_directory=str(export_dir)),
    )
    _seed_files(project_settings, video_id)

    client.delete(f"/api/v1/videos/{video_id}")

    assert exported.read_bytes() == b"mp4 exportado"
    assert export_dir.is_dir()


def test_delete_of_unknown_video_returns_404(client: TestClient) -> None:
    assert client.delete("/api/v1/videos/nao-existe").status_code == 404


def test_purge_only_touches_the_internal_storage(
    project_settings: Settings, tmp_path: Path
) -> None:
    outsider = tmp_path / "fora.mp4"
    outsider.write_bytes(b"nao tocar")

    # Identificador hostil não escapa do storage.
    removed = purge_video_files(project_settings, "../../..")

    assert removed == []
    assert outsider.is_file()
