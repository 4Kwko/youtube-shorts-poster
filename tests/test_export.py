"""Testes da exportação para a pasta escolhida pelo usuário."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.jobs.context import JobContext
from app.jobs.handlers import handle_export
from app.models.enums import ClipStatus, FilenamePattern, JobType, VideoStatus
from app.repositories import ClipRepository, JobRepository, VideoRepository
from app.schemas.settings import VideoSettings
from app.services.export import (
    ExportFailedError,
    InvalidOutputDirectoryError,
    build_filename,
    export_clips,
    resolve_collision,
    sanitize_title,
    validate_output_directory,
)
from app.services.ingest.service import DOWNLOADS_SUBDIR
from app.services.rendering import RENDERS_SUBDIR

# --- filename -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Meu vídeo", "Meu vídeo"),
        ('a\\b/c:d*e?f"g<h>i|j', "a b c d e f g h i j"),
        ("  espaços  ", "espaços"),
        ("termina com ponto...", "termina com ponto"),
        ("", "clip"),
        (None, "clip"),
        ("   ", "clip"),
        ("CON", "clip"),
        ("x" * 200, "x" * 60),
    ],
)
def test_sanitize_title(raw: str | None, expected: str) -> None:
    assert sanitize_title(raw) == expected


def test_filename_patterns() -> None:
    assert build_filename(FilenamePattern.CLIP, 0) == "clip-001.mp4"
    assert build_filename(FilenamePattern.CLIP, 11) == "clip-012.mp4"
    assert build_filename(FilenamePattern.TITLE, 0, "Meu vídeo") == "Meu vídeo-001.mp4"
    # Título hostil nunca vira caminho.
    assert (
        build_filename(FilenamePattern.TITLE, 0, "../../etc/passwd") == ".. .. etc passwd-001.mp4"
    )


def test_collision_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "clip-001.mp4").write_bytes(b"antigo")

    resolved = resolve_collision(tmp_path, "clip-001.mp4")

    assert resolved.name == "clip-001 (2).mp4"
    assert (tmp_path / "clip-001.mp4").read_bytes() == b"antigo"


# --- diretório de saída ---------------------------------------------------


def test_creates_the_output_directory(tmp_path: Path) -> None:
    target = tmp_path / "Videos" / "Clipper"

    resolved = validate_output_directory(str(target))

    assert resolved.is_dir()
    # Nenhum resíduo do teste de escrita.
    assert list(resolved.iterdir()) == []


@pytest.mark.parametrize("raw", ["", "   ", "relativo/saida", "../fora"])
def test_rejects_unusable_paths(raw: str) -> None:
    with pytest.raises(InvalidOutputDirectoryError):
        validate_output_directory(raw)


def test_rejects_a_file_path(tmp_path: Path) -> None:
    target = tmp_path / "arquivo.mp4"
    target.write_bytes(b"x")

    with pytest.raises(InvalidOutputDirectoryError, match="não é uma pasta"):
        validate_output_directory(str(target))


# --- cópia ----------------------------------------------------------------


def _sources(tmp_path: Path, count: int = 3) -> list[tuple[int, Path]]:
    directory = tmp_path / "renders"
    directory.mkdir(parents=True, exist_ok=True)
    sources = []
    for sequence in range(count):
        path = directory / f"{sequence:03d}.mp4"
        path.write_bytes(b"render" * (sequence + 1))
        sources.append((sequence, path))
    return sources


def test_exports_every_clip(tmp_path: Path) -> None:
    destination = validate_output_directory(str(tmp_path / "saida"))

    exported = export_clips(_sources(tmp_path), destination, pattern=FilenamePattern.CLIP)

    assert [item.filename for item in exported] == [
        "clip-001.mp4",
        "clip-002.mp4",
        "clip-003.mp4",
    ]
    assert sorted(p.name for p in destination.iterdir()) == [
        "clip-001.mp4",
        "clip-002.mp4",
        "clip-003.mp4",
    ]


def test_retry_skips_files_already_copied(tmp_path: Path) -> None:
    destination = validate_output_directory(str(tmp_path / "saida"))
    sources = _sources(tmp_path)

    export_clips(sources, destination, pattern=FilenamePattern.CLIP)
    export_clips(sources, destination, pattern=FilenamePattern.CLIP)

    # Nada duplicado: o segundo passe reconhece o que já está lá.
    assert len(list(destination.iterdir())) == 3


def test_missing_render_aborts_the_export(tmp_path: Path) -> None:
    destination = validate_output_directory(str(tmp_path / "saida"))
    sources = _sources(tmp_path)
    sources[1][1].unlink()

    with pytest.raises(ExportFailedError):
        export_clips(sources, destination, pattern=FilenamePattern.CLIP)

    # O primeiro foi copiado, mas nenhum `.part` sobrou.
    assert not any(p.name.endswith(".part") for p in destination.iterdir())


# --- handler --------------------------------------------------------------


def _run_migrations(database_url: str) -> None:
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture
def export_settings(settings: Settings, tmp_path: Path) -> Settings:
    updated = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'export.db'}"})
    updated.ensure_storage_dirs()
    return updated


@pytest.fixture
def engine(export_settings: Settings) -> Iterator[Engine]:
    _run_migrations(export_settings.database_url)
    engine = create_db_engine(export_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "Videos" / "Clipper"


def _make_video(
    settings: Settings,
    session_factory: sessionmaker[Session],
    video_settings: VideoSettings,
) -> JobContext:
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url="https://www.youtube.com/watch?v=abc123",
            provider="youtube",
            status=VideoStatus.RENDERED,
            settings=video_settings,
        )
        video.title = "Meu vídeo"
        video.source_file_key = f"{video.id}/source.mp4"
        clips = ClipRepository(session)
        for sequence in range(2):
            clip = clips.create(
                video_id=video.id,
                sequence=sequence,
                start_time=sequence * 30,
                end_time=sequence * 30 + 30,
            )
            clip.status = ClipStatus.RENDERED
            clip.rendered_file_key = f"{video.id}/{sequence:03d}.mp4"
        job = JobRepository(session).create(video_id=video.id, job_type=JobType.EXPORT)
        video_id, job_id = video.id, job.id

    renders = settings.storage_path(RENDERS_SUBDIR) / video_id
    renders.mkdir(parents=True, exist_ok=True)
    for sequence in range(2):
        (renders / f"{sequence:03d}.mp4").write_bytes(b"render" * (sequence + 1))

    source_dir = settings.storage_path(DOWNLOADS_SUBDIR) / video_id
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source.mp4").write_bytes(b"original")

    return JobContext(
        settings=settings,
        session_factory=session_factory,
        job_id=job_id,
        video_id=video_id,
        job_type=JobType.EXPORT,
    )


def test_handler_exports_and_marks_the_video(
    export_settings: Settings, session_factory: sessionmaker[Session], output_dir: Path
) -> None:
    context = _make_video(
        export_settings,
        session_factory,
        VideoSettings(output_directory=str(output_dir), filename_pattern="title"),
    )

    handle_export(context)

    assert sorted(p.name for p in output_dir.iterdir()) == [
        "Meu vídeo-001.mp4",
        "Meu vídeo-002.mp4",
    ]
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        assert video.status is VideoStatus.EXPORTED
        assert video.progress == 100


def test_keep_original_on_preserves_the_download(
    export_settings: Settings, session_factory: sessionmaker[Session], output_dir: Path
) -> None:
    context = _make_video(
        export_settings,
        session_factory,
        VideoSettings(output_directory=str(output_dir), keep_original=True),
    )

    handle_export(context)

    source = export_settings.storage_path(DOWNLOADS_SUBDIR) / context.video_id / "source.mp4"
    assert source.is_file()
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None and video.source_file_key is not None


def test_keep_original_off_deletes_only_after_a_successful_export(
    export_settings: Settings, session_factory: sessionmaker[Session], output_dir: Path
) -> None:
    context = _make_video(
        export_settings,
        session_factory,
        VideoSettings(output_directory=str(output_dir), keep_original=False),
    )

    handle_export(context)

    source = export_settings.storage_path(DOWNLOADS_SUBDIR) / context.video_id / "source.mp4"
    assert not source.exists()
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        # Sem original, um re-render exige novo download.
        assert video.source_file_key is None
    # Os renders internos e os arquivos exportados continuam intactos.
    assert (
        len(list((export_settings.storage_path(RENDERS_SUBDIR) / context.video_id).iterdir())) == 2
    )
    assert len(list(output_dir.iterdir())) == 2


def test_failed_export_keeps_everything_and_allows_retry(
    export_settings: Settings, session_factory: sessionmaker[Session], output_dir: Path
) -> None:
    context = _make_video(
        export_settings,
        session_factory,
        VideoSettings(output_directory=str(output_dir), keep_original=False),
    )
    # Um render some entre o clipping e a exportação.
    render = export_settings.storage_path(RENDERS_SUBDIR) / context.video_id / "001.mp4"
    render.unlink()

    with pytest.raises(ExportFailedError):
        handle_export(context)

    source = export_settings.storage_path(DOWNLOADS_SUBDIR) / context.video_id / "source.mp4"
    # Falhou: original preservado e vídeo não marcado como exportado.
    assert source.is_file()
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        assert video.status is not VideoStatus.EXPORTED

    # Retry depois que o render volta: termina sem re-renderizar nada.
    render.write_bytes(b"render" * 2)
    handle_export(context)
    assert len(list(output_dir.iterdir())) == 2


def test_export_without_output_directory_is_rejected(
    export_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    context = _make_video(export_settings, session_factory, VideoSettings())

    with pytest.raises(InvalidOutputDirectoryError):
        handle_export(context)


def test_never_deletes_a_file_outside_the_internal_storage(
    export_settings: Settings,
    session_factory: sessionmaker[Session],
    output_dir: Path,
    tmp_path: Path,
) -> None:
    """`source_file_key` apontando para fora do storage não apaga nada."""
    outsider = tmp_path / "arquivo-do-usuario.mp4"
    outsider.write_bytes(b"nao tocar")

    context = _make_video(
        export_settings,
        session_factory,
        VideoSettings(output_directory=str(output_dir), keep_original=False),
    )
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        video.source_file_key = f"../../{outsider.name}"

    handle_export(context)

    assert outsider.read_bytes() == b"nao tocar"
