"""Testes de clipping.

Intervalos e handler rodam sem FFmpeg; há um único teste de integração que
gera um vídeo sintético local, pulado quando o FFmpeg não está disponível.
"""

from __future__ import annotations

import itertools
import shutil
import subprocess
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
from app.jobs.handlers import CLIPS_SUBDIR, handle_clip
from app.models.enums import ClipStatus, JobStatus, JobType, VideoStatus
from app.repositories import ClipRepository, JobRepository, VideoRepository
from app.schemas.settings import VideoSettings
from app.services.clipping import FixedClipper, compute_intervals
from app.services.clipping.clipper import ClipArtifact, build_clip_args, clip_filename
from app.services.clipping.errors import ClipGenerationError, ClipSourceUnavailableError
from app.services.clipping.intervals import ClipInterval
from app.services.ingest.service import DOWNLOADS_SUBDIR
from app.services.media.runner import CommandResult

# --- intervalos (função pura) --------------------------------------------


def _tuples(intervals: list[ClipInterval]) -> list[tuple[int, float, float]]:
    return [(i.sequence, i.start_time, i.end_time) for i in intervals]


def test_exact_multiple_of_clip_duration() -> None:
    assert _tuples(compute_intervals(270, 90)) == [
        (0, 0.0, 90.0),
        (1, 90.0, 180.0),
        (2, 180.0, 270.0),
    ]


def test_remainder_becomes_shorter_last_clip() -> None:
    intervals = compute_intervals(200, 90)

    assert _tuples(intervals) == [(0, 0.0, 90.0), (1, 90.0, 180.0), (2, 180.0, 200.0)]
    assert intervals[-1].duration == 20.0


def test_video_shorter_than_clip_duration_yields_single_clip() -> None:
    intervals = compute_intervals(42.5, 90)

    assert _tuples(intervals) == [(0, 0.0, 42.5)]
    assert intervals[0].duration == 42.5


def test_tiny_remainder_is_absorbed_by_previous_clip() -> None:
    """Um resto de 0.2s viraria um arquivo inútil."""
    intervals = compute_intervals(180.2, 90)

    assert _tuples(intervals) == [(0, 0.0, 90.0), (1, 90.0, 180.2)]


def test_no_interval_exceeds_duration_or_is_empty() -> None:
    intervals = compute_intervals(1000.7, 90)

    assert all(i.duration > 0 for i in intervals)
    assert intervals[-1].end_time == 1000.7
    assert [i.sequence for i in intervals] == list(range(len(intervals)))
    for previous, current in itertools.pairwise(intervals):
        assert previous.end_time == current.start_time


@pytest.mark.parametrize("duration", [0, -1])
def test_invalid_video_duration_is_rejected(duration: float) -> None:
    with pytest.raises(ClipSourceUnavailableError):
        compute_intervals(duration, 90)


def test_invalid_clip_duration_is_rejected() -> None:
    with pytest.raises(ValueError, match="clip_duration"):
        compute_intervals(100, 0)


# --- argumentos do FFmpeg -------------------------------------------------


def test_clip_args_use_reencode_and_exact_window() -> None:
    args = build_clip_args(
        "/usr/bin/ffmpeg", Path("/s/source.mp4"), ClipInterval(1, 90.0, 180.0), Path("/o/001.mp4")
    )

    assert args[0] == "/usr/bin/ffmpeg"
    assert args[args.index("-ss") + 1] == "90.000"
    assert args[args.index("-t") + 1] == "90.000"
    # Stream copy cortaria no keyframe mais próximo.
    assert "copy" not in args
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[-1] == str(Path("/o/001.mp4"))


def test_clip_filenames_sort_naturally() -> None:
    names = [clip_filename(i) for i in (0, 1, 10, 100)]

    assert names == ["000.mp4", "001.mp4", "010.mp4", "100.mp4"]
    assert names == sorted(names)


# --- clipper --------------------------------------------------------------


@pytest.fixture
def clip_settings(settings: Settings, tmp_path: Path) -> Settings:
    updated = settings.model_copy(
        update={
            "database_url": f"sqlite:///{tmp_path / 'clips.db'}",
        }
    )
    updated.ensure_storage_dirs()
    return updated


@pytest.fixture(autouse=True)
def _fake_ffmpeg_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.clipping.clipper.require_ffmpeg", lambda: "/usr/bin/ffmpeg")


def test_clipper_removes_output_dir_when_a_clip_fails(
    monkeypatch: pytest.MonkeyPatch, clip_settings: Settings, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"dados")
    output_dir = tmp_path / "out"
    calls = {"n": 0}

    def _run(args: list[str], timeout: float) -> CommandResult:
        calls["n"] += 1
        if calls["n"] == 2:
            return CommandResult(1, "", "/srv/interno: erro do ffmpeg")
        Path(args[-1]).write_bytes(b"clip")
        return CommandResult(0, "", "")

    monkeypatch.setattr("app.services.clipping.clipper.run_command", _run)
    monkeypatch.setattr("app.services.clipping.clipper.probe_file", lambda p, timeout: None)

    clipper = FixedClipper(clip_settings)
    with pytest.raises(ClipGenerationError) as exc:
        clipper.create_clips(source, compute_intervals(6, 2), output_dir)

    assert "/srv/interno" not in exc.value.message
    assert not output_dir.exists()


def test_clipper_rejects_missing_source(clip_settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(ClipSourceUnavailableError):
        FixedClipper(clip_settings).create_clips(
            tmp_path / "ausente.mp4", compute_intervals(4, 2), tmp_path / "out"
        )


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
def engine(clip_settings: Settings) -> Iterator[Engine]:
    _run_migrations(clip_settings.database_url)
    engine = create_db_engine(clip_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def context(clip_settings: Settings, session_factory: sessionmaker[Session]) -> JobContext:
    """Vídeo já importado, com arquivo de origem no storage."""
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url="https://www.youtube.com/watch?v=abc123",
            provider="youtube",
            status=VideoStatus.DOWNLOADED,
        )
        video.duration = 90.0
        # Configuração por vídeo: clips de 2s para caber no fixture curto.
        video.apply_settings(VideoSettings(clip_duration_seconds=30))
        video.source_file_key = f"{video.id}/source.mp4"
        job = JobRepository(session).create(video_id=video.id, job_type=JobType.CLIP)
        video_id, job_id = video.id, job.id

    source = clip_settings.storage_path(DOWNLOADS_SUBDIR) / video_id
    source.mkdir(parents=True, exist_ok=True)
    (source / "source.mp4").write_bytes(b"conteudo")

    return JobContext(
        settings=clip_settings,
        session_factory=session_factory,
        job_id=job_id,
        video_id=video_id,
        job_type=JobType.CLIP,
    )


def _fake_clipper(monkeypatch: pytest.MonkeyPatch, *, fail_at: int | None = None) -> None:
    def _create_clips(
        self: Any,
        source: Path,
        intervals: list[ClipInterval],
        output_dir: Path,
        *,
        on_clip_done: Any = None,
    ) -> list[ClipArtifact]:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[ClipArtifact] = []
        for index, interval in enumerate(intervals):
            if fail_at is not None and index == fail_at:
                shutil.rmtree(output_dir, ignore_errors=True)
                raise ClipGenerationError("Falha ao gerar um dos clips.")
            path = output_dir / clip_filename(interval.sequence)
            path.write_bytes(b"clip")
            artifacts.append(
                ClipArtifact(
                    interval=interval,
                    path=path,
                    filename=path.name,
                    size_bytes=path.stat().st_size,
                    media_info=None,
                )
            )
            if on_clip_done is not None:
                on_clip_done(len(artifacts), len(intervals))
        return artifacts

    monkeypatch.setattr(FixedClipper, "create_clips", _create_clips)


def test_handler_creates_clip_records_in_order(context: JobContext) -> None:
    handle_clip(context)

    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)
        video = VideoRepository(session).get_by_id(context.video_id)

        assert [clip.sequence for clip in clips] == [0, 1, 2]
        assert [(clip.start_time, clip.end_time) for clip in clips] == [
            (0.0, 30.0),
            (30.0, 60.0),
            (60.0, 90.0),
        ]
        assert all(clip.duration == 30.0 for clip in clips)
        assert all(clip.status is ClipStatus.PENDING for clip in clips)
        # Sem arquivo intermediário: o corte acontece junto com o render.
        assert all(clip.source_file_key is None for clip in clips)
        assert video is not None
        assert video.status is VideoStatus.CLIPPED
        assert video.progress == 100


def test_handler_never_invokes_ffmpeg(monkeypatch: pytest.MonkeyPatch, context: JobContext) -> None:
    """A etapa de clipping é só metadata — nenhum encode acontece aqui."""

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("clipping não deve invocar FFmpeg")

    monkeypatch.setattr("app.services.media.runner.subprocess.run", _forbidden)
    monkeypatch.setattr(FixedClipper, "create_clips", _forbidden)

    handle_clip(context)

    clips_dir = context.settings.storage_path(CLIPS_SUBDIR) / context.video_id
    assert not clips_dir.exists()


def test_handler_is_fast_for_long_videos(context: JobContext) -> None:
    """Vídeo de 3h: 360 registros, nenhum encode."""
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        video.duration = 3 * 60 * 60

    handle_clip(context)

    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)
    assert len(clips) == 360
    assert not (context.settings.storage_path(CLIPS_SUBDIR) / context.video_id).exists()


def test_rerun_does_not_duplicate_clips(context: JobContext) -> None:
    """Retry: registros da tentativa anterior são descartados."""
    handle_clip(context)
    handle_clip(context)

    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)

    assert len(clips) == 3
    assert len({clip.sequence for clip in clips}) == 3


def test_handler_requires_imported_video(context: JobContext) -> None:
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        video.source_file_key = None

    with pytest.raises(ClipSourceUnavailableError):
        handle_clip(context)


def test_clip_job_type_is_dispatched() -> None:
    assert handlers_module.HANDLERS[JobType.CLIP] is handle_clip


# --- integração real com FFmpeg ------------------------------------------


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/FFprobe não disponíveis",
)
def test_real_clipping_produces_playable_files(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    monkeypatch.undo()  # usa o ffmpeg de verdade, não o caminho falso
    settings.ensure_storage_dirs()
    source = tmp_path / "source.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=25:duration=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=5",
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

    intervals = compute_intervals(5.0, 2.0)
    artifacts = FixedClipper(settings).create_clips(source, intervals, tmp_path / "clips")

    assert len(artifacts) == 3
    for artifact in artifacts:
        assert artifact.size_bytes > 0
        assert artifact.media_info is not None
        assert artifact.media_info.video_codec == "h264"
        assert artifact.media_info.audio_codec == "aac"
        assert artifact.media_info.duration_seconds is not None
        # Re-encode: a duração real fica próxima da pedida.
        assert abs(artifact.media_info.duration_seconds - artifact.interval.duration) < 0.5


def test_clipping_enqueues_render_job(monkeypatch: pytest.MonkeyPatch, context: JobContext) -> None:
    _fake_clipper(monkeypatch)

    handle_clip(context)

    with session_scope(context.session_factory) as session:
        jobs = JobRepository(session).list_for_video(context.video_id)
        render_jobs = [job for job in jobs if job.job_type is JobType.RENDER]

    assert len(render_jobs) == 1
    assert render_jobs[0].status is JobStatus.QUEUED


def test_rerun_does_not_duplicate_render_job(context: JobContext) -> None:
    handle_clip(context)
    handle_clip(context)

    with session_scope(context.session_factory) as session:
        jobs = JobRepository(session).list_for_video(context.video_id)

    assert len([job for job in jobs if job.job_type is JobType.RENDER]) == 1
