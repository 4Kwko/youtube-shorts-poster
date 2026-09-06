"""Testes da importação de arquivo local."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import session_scope
from app.jobs.context import JobContext
from app.jobs.handlers import handle_ingest
from app.main import create_app
from app.models.enums import JobType, SourceType, VideoStatus
from app.repositories import JobRepository, VideoRepository
from app.services.ingest.errors import (
    InvalidVideoURLError,
    VideoDownloadError,
    VideoTooLargeError,
)
from app.services.ingest.local import import_local_file, validate_local_source
from app.services.ingest.service import DOWNLOADS_SUBDIR

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/FFprobe não disponíveis",
)


def _run_migrations(database_url: str) -> None:
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture
def local_settings(settings: Settings, tmp_path: Path) -> Settings:
    database_url = f"sqlite:///{tmp_path / 'local.db'}"
    _run_migrations(database_url)
    updated = settings.model_copy(update={"database_url": database_url})
    updated.ensure_storage_dirs()
    return updated


@pytest.fixture
def app(local_settings: Settings) -> FastAPI:
    return create_app(local_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(app: FastAPI) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = app.state.session_factory
    return factory


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """Vídeo sintético de 2s, fora do storage do app."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg não disponível")

    source = tmp_path / "meus videos" / "entrevista.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return source


# --- validação ------------------------------------------------------------


@requires_ffmpeg
def test_accepts_a_real_video_file(local_settings: Settings, sample_video: Path) -> None:
    assert validate_local_source(local_settings, str(sample_video)) == sample_video


def test_rejects_a_missing_file(local_settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(InvalidVideoURLError, match="não encontrado"):
        validate_local_source(local_settings, str(tmp_path / "ausente.mp4"))


def test_rejects_a_directory(local_settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(InvalidVideoURLError, match="não uma pasta"):
        validate_local_source(local_settings, str(tmp_path))


def test_rejects_a_relative_path(local_settings: Settings) -> None:
    with pytest.raises(InvalidVideoURLError, match="seletor"):
        validate_local_source(local_settings, "videos/entrevista.mp4")


def test_rejects_an_unsupported_extension(local_settings: Settings, tmp_path: Path) -> None:
    document = tmp_path / "planilha.xlsx"
    document.write_bytes(b"conteudo")

    with pytest.raises(InvalidVideoURLError, match="Formato não suportado"):
        validate_local_source(local_settings, str(document))


def test_rejects_an_empty_file(local_settings: Settings, tmp_path: Path) -> None:
    empty = tmp_path / "vazio.mp4"
    empty.touch()

    with pytest.raises(InvalidVideoURLError, match="vazio"):
        validate_local_source(local_settings, str(empty))


def test_rejects_a_file_above_the_size_limit(settings: Settings, tmp_path: Path) -> None:
    limited = settings.model_copy(update={"max_video_file_size_bytes": 10})
    big = tmp_path / "grande.mp4"
    big.write_bytes(b"x" * 100)

    with pytest.raises(VideoTooLargeError):
        validate_local_source(limited, str(big))


@requires_ffmpeg
def test_extension_alone_does_not_make_it_a_video(local_settings: Settings, tmp_path: Path) -> None:
    """Extensão enganosa: quem decide é o ffprobe."""
    fake = tmp_path / "nao-e-video.mp4"
    fake.write_text("isto é texto")

    # Passa na validação estrutural...
    validate_local_source(local_settings, str(fake))

    # ...e é recusado na importação.
    with pytest.raises(VideoDownloadError, match="ler este arquivo"):
        import_local_file(local_settings, "v" * 32, str(fake))


# --- importação -----------------------------------------------------------


@requires_ffmpeg
def test_import_copies_into_the_internal_storage(
    local_settings: Settings, sample_video: Path
) -> None:
    original = sample_video.read_bytes()

    info = import_local_file(local_settings, "a" * 32, str(sample_video))

    copy = local_settings.storage_path(DOWNLOADS_SUBDIR) / ("a" * 32) / "source.mp4"
    assert copy.is_file()
    assert copy.read_bytes() == original
    # O arquivo do usuário permanece intocado.
    assert sample_video.read_bytes() == original

    assert info.provider == "local"
    assert info.local_filename == "source.mp4"
    assert info.title == "entrevista"
    assert info.provider_video_id is None
    assert (info.width, info.height) == (640, 360)
    assert info.video_codec == "h264"


@requires_ffmpeg
def test_import_reports_progress_while_copying(
    local_settings: Settings, sample_video: Path
) -> None:
    seen: list[int] = []

    import_local_file(
        local_settings,
        "b" * 32,
        str(sample_video),
        on_progress=lambda stage, progress: seen.append(progress),
    )

    assert seen[0] == 5
    assert seen[-1] == 100
    assert seen == sorted(seen)


@requires_ffmpeg
def test_import_rejects_a_video_longer_than_the_limit(
    local_settings: Settings, sample_video: Path
) -> None:
    limited = local_settings.model_copy(update={"max_video_duration_seconds": 1.0})

    with pytest.raises(Exception, match="mais longo"):
        import_local_file(limited, "c" * 32, str(sample_video))

    # Nada foi copiado: a recusa acontece antes.
    assert not (limited.storage_path(DOWNLOADS_SUBDIR) / ("c" * 32) / "source.mp4").exists()


@requires_ffmpeg
def test_failed_copy_leaves_no_partial_file(
    monkeypatch: pytest.MonkeyPatch, local_settings: Settings, sample_video: Path
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("disco cheio")

    monkeypatch.setattr("app.services.ingest.local._copy_in_chunks", _boom)

    with pytest.raises(VideoDownloadError):
        import_local_file(local_settings, "d" * 32, str(sample_video))

    assert not (local_settings.storage_path(DOWNLOADS_SUBDIR) / ("d" * 32) / "source.mp4").exists()
    assert sample_video.is_file()


# --- API ------------------------------------------------------------------


@requires_ffmpeg
def test_local_endpoint_creates_projects_and_jobs(
    client: TestClient, session_factory: sessionmaker[Session], sample_video: Path
) -> None:
    response = client.post("/api/v1/videos/local", json={"paths": [str(sample_video)]})

    assert response.status_code == 202
    video = response.json()["videos"][0]
    assert video["source_type"] == "local"
    assert video["source_url"] is None
    assert video["title"] == "entrevista"

    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_for_video(video["id"])
        assert [job.job_type for job in jobs] == [JobType.INGEST]


@requires_ffmpeg
def test_local_endpoint_carries_the_settings_snapshot(
    client: TestClient, session_factory: sessionmaker[Session], sample_video: Path
) -> None:
    body = client.post(
        "/api/v1/videos/local",
        json={"paths": [str(sample_video)], "settings": {"clip_duration_seconds": 120}},
    ).json()

    with session_scope(session_factory) as session:
        stored = VideoRepository(session).get_by_id(body["videos"][0]["id"])
        assert stored is not None
        assert stored.settings.clip_duration_seconds == 120
        assert stored.source_type is SourceType.LOCAL


def test_local_endpoint_rejects_everything_when_one_path_is_invalid(
    client: TestClient, session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    response = client.post(
        "/api/v1/videos/local",
        json={"paths": [str(tmp_path / "ausente.mp4")]},
    )

    assert response.status_code == 422
    with session_scope(session_factory) as session:
        assert VideoRepository(session).list() == []


@requires_ffmpeg
def test_local_endpoint_collapses_duplicate_paths(client: TestClient, sample_video: Path) -> None:
    videos = client.post(
        "/api/v1/videos/local", json={"paths": [str(sample_video), str(sample_video)]}
    ).json()["videos"]

    assert len(videos) == 1


# --- pipeline -------------------------------------------------------------


@requires_ffmpeg
def test_ingest_handler_imports_the_local_file(
    client: TestClient,
    session_factory: sessionmaker[Session],
    local_settings: Settings,
    sample_video: Path,
) -> None:
    body = client.post("/api/v1/videos/local", json={"paths": [str(sample_video)]}).json()
    video_id = body["videos"][0]["id"]

    with session_scope(session_factory) as session:
        job = JobRepository(session).list_for_video(video_id)[0]
        job_id = job.id

    handle_ingest(
        JobContext(
            settings=local_settings,
            session_factory=session_factory,
            job_id=job_id,
            video_id=video_id,
            job_type=JobType.INGEST,
        )
    )

    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(video_id)
        assert video is not None
        assert video.status is VideoStatus.DOWNLOADED
        assert video.source_file_key == f"{video_id}/source.mp4"
        assert video.width == 640
        # O caminho externo é descartado assim que a cópia existe.
        assert video.import_path is None
        # Encadeou a transcrição como qualquer outro vídeo.
        jobs = JobRepository(session).list_for_video(video_id)
        assert JobType.TRANSCRIBE in [job.job_type for job in jobs]

    assert sample_video.is_file()


@requires_ffmpeg
def test_deleting_a_local_project_never_touches_the_original(
    client: TestClient,
    session_factory: sessionmaker[Session],
    local_settings: Settings,
    sample_video: Path,
) -> None:
    body = client.post("/api/v1/videos/local", json={"paths": [str(sample_video)]}).json()
    video_id = body["videos"][0]["id"]

    with session_scope(session_factory) as session:
        job = JobRepository(session).list_for_video(video_id)[0]
        job_id = job.id
    handle_ingest(
        JobContext(
            settings=local_settings,
            session_factory=session_factory,
            job_id=job_id,
            video_id=video_id,
            job_type=JobType.INGEST,
        )
    )

    assert client.delete(f"/api/v1/videos/{video_id}").status_code == 204

    # A cópia interna some; o arquivo do usuário fica.
    assert not (local_settings.storage_path(DOWNLOADS_SUBDIR) / video_id).exists()
    assert sample_video.is_file()
