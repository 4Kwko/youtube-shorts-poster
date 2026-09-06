"""Testes da renderização vertical.

Filtro e handler rodam sem FFmpeg; há testes de integração reais com vídeos
sintéticos de três proporções, pulados quando o FFmpeg não está disponível.
"""

from __future__ import annotations

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
from app.jobs.handlers import handle_render
from app.models.enums import ClipStatus, JobType, VideoStatus
from app.repositories import ClipRepository, JobRepository, VideoRepository
from app.schemas.settings import VideoSettings
from app.services.ingest.service import DOWNLOADS_SUBDIR
from app.services.media.runner import CommandResult
from app.services.rendering import (
    DEFAULT_LAYOUT,
    RENDERS_SUBDIR,
    VerticalLayout,
    VerticalRenderer,
    build_center_crop_filter,
    build_filtergraph,
    build_render_args,
    plan_layout,
)
from app.services.rendering.errors import RenderFailedError, RenderSourceUnavailableError

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/FFprobe não disponíveis",
)


# --- filtro (função pura) -------------------------------------------------


def test_center_crop_filter_fills_and_crops() -> None:
    video_filter = build_center_crop_filter(1080, 1920)

    assert "scale=1080:1920:force_original_aspect_ratio=increase" in video_filter
    assert "crop=1080:1920" in video_filter
    assert "setsar=1" in video_filter
    # `pad` produziria barras pretas; `decrease` deixaria o quadro incompleto.
    assert "pad" not in video_filter
    assert "decrease" not in video_filter


def test_filter_rejects_invalid_dimensions() -> None:
    with pytest.raises(ValueError, match="positivas"):
        build_center_crop_filter(0, 1920)


def test_render_args_encode_h264_and_aac() -> None:
    plan = plan_layout(1920, 1080)
    args = build_render_args(
        "/usr/bin/ffmpeg",
        Path("/in/000.mp4"),
        Path("/out/000.mp4"),
        plan=plan,
    )

    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[args.index("-filter_complex") + 1] == build_filtergraph(plan)
    # A saída do grafo é mapeada explicitamente; `0:a?` mantém o áudio.
    assert args[args.index("-map") + 1] == "[v]"
    assert "0:a?" in args
    assert args[-1] == "/out/000.mp4"


# --- renderer -------------------------------------------------------------


@pytest.fixture
def render_settings(settings: Settings, tmp_path: Path) -> Settings:
    updated = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'render.db'}"})
    updated.ensure_storage_dirs()
    return updated


def test_renderer_rejects_missing_source(
    monkeypatch: pytest.MonkeyPatch, render_settings: Settings, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.services.rendering.renderer.require_ffmpeg", lambda: "/usr/bin/ffmpeg")

    with pytest.raises(RenderSourceUnavailableError):
        VerticalRenderer(render_settings).render(tmp_path / "ausente.mp4", tmp_path / "out.mp4")


def test_renderer_discards_partial_output_on_failure(
    monkeypatch: pytest.MonkeyPatch, render_settings: Settings, tmp_path: Path
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"dados")
    output = tmp_path / "render.mp4"

    def _run(args: list[str], timeout: float) -> CommandResult:
        Path(args[-1]).write_bytes(b"parcial")
        return CommandResult(1, "", "/srv/interno: erro do ffmpeg")

    monkeypatch.setattr("app.services.rendering.renderer.require_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.services.rendering.renderer.run_command", _run)

    with pytest.raises(RenderFailedError) as exc:
        VerticalRenderer(render_settings).render(source, output)

    assert "/srv/interno" not in exc.value.message
    assert not output.exists()


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
def engine(render_settings: Settings) -> Iterator[Engine]:
    _run_migrations(render_settings.database_url)
    engine = create_db_engine(render_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def context(render_settings: Settings, session_factory: sessionmaker[Session]) -> JobContext:
    """Vídeo já clipado, com três arquivos de clip no storage."""
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url="https://www.youtube.com/watch?v=abc123",
            provider="youtube",
            status=VideoStatus.CLIPPED,
        )
        video.duration = 90.0
        video.apply_settings(VideoSettings(clip_duration_seconds=30))
        # 16:9: exercita o layout padrão com fundo desfocado.
        video.width, video.height = 1280, 720
        video.source_file_key = f"{video.id}/source.mp4"
        clips = ClipRepository(session)
        for sequence in range(3):
            clips.create(
                video_id=video.id,
                sequence=sequence,
                start_time=sequence * 2,
                end_time=sequence * 2 + 2,
            )
        job = JobRepository(session).create(video_id=video.id, job_type=JobType.RENDER)
        video_id, job_id = video.id, job.id

    # A fonte agora é o vídeo original, não um clip intermediário.
    source_dir = render_settings.storage_path(DOWNLOADS_SUBDIR) / video_id
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source.mp4").write_bytes(b"video original")

    return JobContext(
        settings=render_settings,
        session_factory=session_factory,
        job_id=job_id,
        video_id=video_id,
        job_type=JobType.RENDER,
    )


def _fake_renderer(monkeypatch: pytest.MonkeyPatch, *, fail_at: int | None = None) -> list[Path]:
    rendered: list[Path] = []

    def _render(self: Any, source: Path, output: Path, **kwargs: Any) -> Any:
        if fail_at is not None and len(rendered) == fail_at:
            raise RenderFailedError("Falha ao renderizar o clip.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"render")
        rendered.append(output)
        return None

    monkeypatch.setattr(VerticalRenderer, "render", _render)
    monkeypatch.setattr(VerticalRenderer, "__init__", lambda self, settings: None)
    return rendered


def test_handler_renders_every_clip_and_persists_keys(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    _fake_renderer(monkeypatch)

    handle_render(context)

    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)
        video = VideoRepository(session).get_by_id(context.video_id)

        assert [clip.rendered_file_key for clip in clips] == [
            f"{context.video_id}/000.mp4",
            f"{context.video_id}/001.mp4",
            f"{context.video_id}/002.mp4",
        ]
        assert all(clip.status is ClipStatus.RENDERED for clip in clips)
        assert video is not None
        assert video.status is VideoStatus.RENDERED
        assert video.progress == 100


def test_render_enqueues_all_clips_once_for_youtube(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    from app.services.youtube import ledger

    context.settings.youtube_auto_publish = True
    _fake_renderer(monkeypatch)
    handle_render(context)
    handle_render(context)
    with ledger(context.settings) as db:
        rows = db.execute("SELECT * FROM uploads").fetchall()
    assert len(rows) == 3
    assert all(row["state"] == "queued" for row in rows)
    assert all(row["privacy"] == "public" for row in rows)


def test_render_without_youtube_enabled_does_not_queue(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    _fake_renderer(monkeypatch)
    handle_render(context)
    assert not (context.settings.storage_root / "youtube-uploads.db").exists()


def test_render_reads_original_video_with_clip_interval(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    """Uma passagem por clip, direto do original — sem intermediário horizontal."""
    calls: list[tuple[str, float | None, float | None]] = []

    def _render(self: Any, source: Path, output: Path, **kwargs: Any) -> Any:
        calls.append((source.name, kwargs.get("start_time"), kwargs.get("duration")))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"render")
        return None

    monkeypatch.setattr(VerticalRenderer, "render", _render)
    monkeypatch.setattr(VerticalRenderer, "__init__", lambda self, settings: None)

    handle_render(context)

    assert calls == [
        ("source.mp4", 0.0, 2.0),
        ("source.mp4", 2.0, 2.0),
        ("source.mp4", 4.0, 2.0),
    ]
    source = context.settings.storage_path(DOWNLOADS_SUBDIR) / context.video_id / "source.mp4"
    assert source.read_bytes() == b"video original"

    renders_dir = context.settings.storage_path(RENDERS_SUBDIR) / context.video_id
    assert sorted(p.name for p in renders_dir.iterdir()) == ["000.mp4", "001.mp4", "002.mp4"]


def test_retry_skips_clips_already_rendered(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    """Falha no meio: o retry completa o que faltou em vez de refazer tudo."""
    _fake_renderer(monkeypatch, fail_at=2)
    with pytest.raises(RenderFailedError):
        handle_render(context)

    with session_scope(context.session_factory) as session:
        statuses = [
            clip.status for clip in ClipRepository(session).list_for_video(context.video_id)
        ]
    assert statuses == [ClipStatus.RENDERED, ClipStatus.RENDERED, ClipStatus.FAILED]

    rendered = _fake_renderer(monkeypatch)
    handle_render(context)

    # Só o clip que faltava foi renderizado de novo.
    assert len(rendered) == 1
    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)
        assert len(clips) == 3
        assert all(clip.status is ClipStatus.RENDERED for clip in clips)


def test_handler_requires_clips(monkeypatch: pytest.MonkeyPatch, context: JobContext) -> None:
    _fake_renderer(monkeypatch)
    with session_scope(context.session_factory) as session:
        ClipRepository(session).delete_for_video(context.video_id)

    with pytest.raises(RenderSourceUnavailableError):
        handle_render(context)


def test_render_job_type_is_dispatched() -> None:
    assert handlers_module.HANDLERS[JobType.RENDER] is handle_render


# --- integração real ------------------------------------------------------


@requires_ffmpeg
@pytest.mark.parametrize(
    ("size", "label"),
    [("640x360", "16:9"), ("360x640", "9:16"), ("480x480", "quadrado")],
)
def test_real_render_always_outputs_1080x1920(
    settings: Settings, tmp_path: Path, size: str, label: str
) -> None:
    settings.ensure_storage_dirs()
    source = tmp_path / f"{label}.mp4"
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
            f"testsrc=size={size}:rate=25:duration=2",
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

    result = VerticalRenderer(settings).render(source, tmp_path / f"out-{label}.mp4")

    assert result.media_info is not None
    assert (result.media_info.width, result.media_info.height) == (1080, 1920)
    assert result.media_info.video_codec == "h264"
    assert result.media_info.audio_codec == "aac"
    assert result.media_info.duration_seconds is not None
    assert abs(result.media_info.duration_seconds - 2.0) < 0.5
    assert result.size_bytes > 0


def test_render_args_trim_the_source_interval() -> None:
    args = build_render_args(
        "/usr/bin/ffmpeg",
        Path("/in/source.mp4"),
        Path("/out/001.mp4"),
        plan=plan_layout(1920, 1080),
        start_time=90.0,
        duration=90.0,
    )

    # `-ss` antes do `-i` (busca rápida) e `-t` depois: um encode só.
    assert args.index("-ss") < args.index("-i") < args.index("-t")
    assert args[args.index("-ss") + 1] == "90.000"
    assert args[args.index("-t") + 1] == "90.000"


@requires_ffmpeg
def test_real_render_of_interval_from_original(settings: Settings, tmp_path: Path) -> None:
    """Corte + vertical numa passagem: um único encode por clip final."""
    settings.ensure_storage_dirs()
    source = tmp_path / "original.mp4"
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
            "testsrc=size=640x360:rate=25:duration=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
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

    result = VerticalRenderer(settings).render(
        source, tmp_path / "002.mp4", start_time=4.0, duration=2.0
    )

    assert result.media_info is not None
    assert (result.media_info.width, result.media_info.height) == (1080, 1920)
    assert result.media_info.video_codec == "h264"
    assert result.media_info.audio_codec == "aac"
    assert result.media_info.duration_seconds is not None
    assert abs(result.media_info.duration_seconds - 2.0) < 0.5


@requires_ffmpeg
def test_pipeline_clip_then_render_uses_one_encode_per_clip(
    settings: Settings, tmp_path: Path
) -> None:
    """Smoke do fluxo novo: clip só grava metadata, render encoda uma vez cada."""
    from app.jobs.handlers import handle_clip

    database_url = f"sqlite:///{tmp_path / 'pipeline.db'}"
    _run_migrations(database_url)
    pipeline_settings = settings.model_copy(update={"database_url": database_url})
    pipeline_settings.ensure_storage_dirs()
    engine = create_db_engine(pipeline_settings)
    factory = create_session_factory(engine)

    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None

    with session_scope(factory) as session:
        video = VideoRepository(session).create(
            source_url="https://www.youtube.com/watch?v=abc123",
            provider="youtube",
            status=VideoStatus.DOWNLOADED,
        )
        # Fonte sintética de 6s: um clip só, com o mínimo de 30s.
        video.duration = 6.0
        video.apply_settings(VideoSettings(clip_duration_seconds=30))
        video.width, video.height = 640, 360
        video.source_file_key = f"{video.id}/source.mp4"
        clip_job = JobRepository(session).create(video_id=video.id, job_type=JobType.CLIP)
        video_id, clip_job_id = video.id, clip_job.id

    source_dir = pipeline_settings.storage_path(DOWNLOADS_SUBDIR) / video_id
    source_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25:duration=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(source_dir / "source.mp4"),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )

    clip_context = JobContext(
        settings=pipeline_settings,
        session_factory=factory,
        job_id=clip_job_id,
        video_id=video_id,
        job_type=JobType.CLIP,
    )
    handle_clip(clip_context)

    with session_scope(factory) as session:
        render_job = next(
            job
            for job in JobRepository(session).list_for_video(video_id)
            if job.job_type is JobType.RENDER
        )
        render_job_id = render_job.id

    handle_render(
        JobContext(
            settings=pipeline_settings,
            session_factory=factory,
            job_id=render_job_id,
            video_id=video_id,
            job_type=JobType.RENDER,
        )
    )

    with session_scope(factory) as session:
        clips = ClipRepository(session).list_for_video(video_id)
        video_row = VideoRepository(session).get_by_id(video_id)

        assert len(clips) == 1
        assert all(clip.status is ClipStatus.RENDERED for clip in clips)
        assert all(clip.rendered_file_key is not None for clip in clips)
        assert video_row is not None
        assert video_row.status is VideoStatus.RENDERED

    renders = sorted((pipeline_settings.storage_path(RENDERS_SUBDIR) / video_id).iterdir())
    assert [p.name for p in renders] == ["000.mp4"]

    from app.services.media.probe import probe_file

    for path in renders:
        info = probe_file(path, timeout=30)
        assert (info.width, info.height) == (1080, 1920)
        assert info.audio_codec == "aac"

    # Nenhum arquivo intermediário foi escrito.
    clips_root = pipeline_settings.storage_path("clips")
    assert not (clips_root / video_id).exists()

    engine.dispose()


# --- legendas queimadas ---------------------------------------------------


def _seed_transcript(context: JobContext) -> None:
    from app.repositories import TranscriptRepository
    from app.schemas.transcript import TranscriptResult, TranscriptSegment, TranscriptWord
    from app.services.transcription import write_transcript

    transcript = TranscriptResult(
        language="pt",
        duration=6.0,
        segments=[
            TranscriptSegment(
                start=0.5,
                end=3.0,
                text="Atenção total agora.",
                words=[
                    TranscriptWord(start=0.5, end=1.2, word="Atenção"),
                    TranscriptWord(start=1.2, end=2.0, word="total"),
                    TranscriptWord(start=2.0, end=3.0, word="agora."),
                ],
            )
        ],
    )
    file_key = write_transcript(context.settings, context.video_id, transcript)
    with session_scope(context.session_factory) as session:
        TranscriptRepository(session).upsert(
            video_id=context.video_id, file_key=file_key, language="pt"
        )


def test_render_burns_subtitles_in_a_single_ffmpeg_call(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    """Corte, crop e legenda saem em uma passagem só por clip."""
    from app.services.subtitles.storage import SUBTITLES_SUBDIR

    _seed_transcript(context)
    invocations: list[list[str]] = []

    def _run(args: list[str], timeout: float) -> CommandResult:
        invocations.append(args)
        Path(args[-1]).write_bytes(b"render")
        return CommandResult(0, "", "")

    monkeypatch.setattr("app.services.rendering.renderer.require_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.services.rendering.renderer.run_command", _run)
    monkeypatch.setattr("app.services.rendering.renderer.probe_file", lambda p, timeout: None)

    handle_render(context)

    # Três clips, três invocações — nenhum encode intermediário.
    assert len(invocations) == 3
    first = invocations[0]
    video_filter = first[first.index("-filter_complex") + 1]
    assert "overlay=" in video_filter
    assert "subtitles=filename=" in video_filter
    assert first[first.index("-ss") + 1] == "0.000"

    subtitle = context.settings.storage_path(SUBTITLES_SUBDIR) / context.video_id / "000.ass"
    assert subtitle.is_file()
    assert "Atenção" in subtitle.read_text(encoding="utf-8")


def test_clip_without_speech_renders_without_subtitles(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    _seed_transcript(context)  # fala só até 3s, ou seja, apenas no primeiro clip
    filters: list[str] = []

    def _run(args: list[str], timeout: float) -> CommandResult:
        filters.append(args[args.index("-filter_complex") + 1])
        Path(args[-1]).write_bytes(b"render")
        return CommandResult(0, "", "")

    monkeypatch.setattr("app.services.rendering.renderer.require_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.services.rendering.renderer.run_command", _run)
    monkeypatch.setattr("app.services.rendering.renderer.probe_file", lambda p, timeout: None)

    handle_render(context)

    assert "subtitles=" in filters[0]
    # Clips 2 e 3 não têm fala: renderizam mesmo assim, sem legenda.
    assert "subtitles=" not in filters[2]


def test_render_without_transcript_still_produces_clips(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    _fake_renderer(monkeypatch)

    handle_render(context)

    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)
    assert all(clip.rendered_file_key is not None for clip in clips)


def test_subtitle_failure_marks_clip_failed(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    _seed_transcript(context)

    def _boom(self: Any, *args: Any, **kwargs: Any) -> None:
        raise RenderFailedError("Falha ao renderizar o clip.")

    monkeypatch.setattr(VerticalRenderer, "__init__", lambda self, settings: None)
    monkeypatch.setattr(VerticalRenderer, "render", _boom)

    with pytest.raises(RenderFailedError):
        handle_render(context)

    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)
    assert clips[0].status is ClipStatus.FAILED


@requires_ffmpeg
def test_real_render_with_burned_subtitles(settings: Settings, tmp_path: Path) -> None:
    """Vídeo sintético + `.ass` real: resolução, codecs e duração preservados."""
    from app.schemas.transcript import TranscriptResult, TranscriptSegment, TranscriptWord
    from app.services.subtitles import build_ass, build_events

    settings.ensure_storage_dirs()
    source = tmp_path / "original.mp4"
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
            "testsrc=size=640x360:rate=25:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
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

    events = build_events(
        TranscriptResult(
            duration=2.0,
            segments=[
                TranscriptSegment(
                    start=0.0,
                    end=1.8,
                    text="Atenção {total}",
                    words=[
                        TranscriptWord(start=0.0, end=0.9, word="Atenção"),
                        TranscriptWord(start=0.9, end=1.8, word="{total}"),
                    ],
                )
            ],
        )
    )
    subtitle = tmp_path / "000.ass"
    subtitle.write_text(build_ass(events), encoding="utf-8")

    result = VerticalRenderer(settings).render(
        source,
        tmp_path / "out.mp4",
        start_time=1.0,
        duration=2.0,
        subtitles=subtitle,
    )

    assert result.media_info is not None
    assert (result.media_info.width, result.media_info.height) == (1080, 1920)
    assert result.media_info.video_codec == "h264"
    assert result.media_info.audio_codec == "aac"
    assert result.media_info.duration_seconds is not None
    assert abs(result.media_info.duration_seconds - 2.0) < 0.5


# --- layout blurred_4_3 ---------------------------------------------------


def test_sixteen_by_nine_crops_sideways_to_four_thirds() -> None:
    plan = plan_layout(1920, 1080)

    assert plan.layout is VerticalLayout.BLURRED_4_3
    # Crop central das laterais: altura intacta, largura = altura * 4/3.
    assert (plan.crop_width, plan.crop_height) == (1440, 1080)
    assert (plan.foreground_width, plan.foreground_height) == (1080, 810)


def test_foreground_keeps_the_source_proportion() -> None:
    """Sem stretch: a proporção do foreground é a do recorte."""
    plan = plan_layout(1920, 1080)
    crop_width, crop_height = plan.crop_width, plan.crop_height
    foreground_width, foreground_height = plan.foreground_width, plan.foreground_height

    assert crop_width is not None and crop_height is not None
    assert foreground_width is not None and foreground_height is not None
    crop_aspect = crop_width / crop_height
    foreground_aspect = foreground_width / foreground_height
    assert abs(crop_aspect - foreground_aspect) < 0.01
    assert abs(crop_aspect - 4 / 3) < 0.01


def test_four_thirds_source_is_not_cropped() -> None:
    plan = plan_layout(1440, 1080)

    assert (plan.crop_width, plan.crop_height) == (1440, 1080)
    assert (plan.foreground_width, plan.foreground_height) == (1080, 810)


def test_square_source_keeps_square_foreground() -> None:
    plan = plan_layout(1080, 1080)

    assert (plan.foreground_width, plan.foreground_height) == (1080, 1080)
    assert (plan.crop_width, plan.crop_height) == (1080, 1080)


def test_vertical_source_fills_the_canvas_without_background() -> None:
    plan = plan_layout(1080, 1920)

    assert plan.layout is VerticalLayout.CENTER_CROP
    assert plan.uses_background is False


def test_center_crop_is_still_available_as_an_option() -> None:
    plan = plan_layout(1920, 1080, VerticalLayout.CENTER_CROP)

    assert plan.layout is VerticalLayout.CENTER_CROP
    assert plan.uses_background is False
    assert "crop=1080:1920" in build_filtergraph(plan)


def test_default_layout_is_blurred() -> None:
    assert DEFAULT_LAYOUT is VerticalLayout.BLURRED_4_3


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 1080), (1080, 1080), (1280, 720), (2560, 1080)],
)
def test_foreground_dimensions_are_even(width: int, height: int) -> None:
    """yuv420p rejeita dimensão ímpar."""
    plan = plan_layout(width, height)

    for value in (plan.foreground_width, plan.foreground_height, plan.crop_width, plan.crop_height):
        assert value is None or value % 2 == 0


@pytest.mark.parametrize(("width", "height"), [(0, 1080), (1920, 0), (-10, 100)])
def test_invalid_source_dimensions_are_rejected(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="positivas"):
        plan_layout(width, height)


def test_blurred_graph_has_one_source_two_branches_and_an_overlay() -> None:
    graph = build_filtergraph(plan_layout(1920, 1080))

    assert graph.startswith("[0:v]split=2[bg][fg]")
    assert "gblur=" in graph
    # O fundo cobre o canvas inteiro: nunca sobra barra preta.
    assert "crop=410:730" in graph and "scale=1080:1920" in graph
    assert "crop=1440:1080,scale=1080:810" in graph
    assert "overlay=(W-w)/2:(H-h)/2" in graph
    assert graph.endswith("[v]")


@requires_ffmpeg
def test_real_blurred_render_of_sixteen_by_nine(settings: Settings, tmp_path: Path) -> None:
    """Fonte branca 16:9: o foreground vira uma faixa nítida no centro."""
    from PIL import Image

    settings.ensure_storage_dirs()
    source = tmp_path / "white.mp4"
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
            "color=c=white:size=1280x720:rate=25:duration=2",
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

    output = tmp_path / "out.mp4"
    result = VerticalRenderer(settings).render(source, output, source_size=(1280, 720))

    assert result.media_info is not None
    assert (result.media_info.width, result.media_info.height) == (1080, 1920)
    assert result.media_info.video_codec == "h264"
    assert result.media_info.audio_codec == "aac"

    frame = tmp_path / "frame.png"
    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-y",
            str(frame),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )

    image = Image.open(frame).convert("L")
    assert image.size == (1080, 1920)

    column: list[int] = [int(image.getpixel((540, y))) for y in range(1920)]  # type: ignore[arg-type]
    bright = [y for y, value in enumerate(column) if value > 240]

    # Faixa nítida de 810px (1080 em 4:3), centralizada no canvas.
    assert abs((bright[-1] - bright[0] + 1) - 810) <= 4
    assert abs(bright[0] - (1920 - 810) // 2) <= 4
    # Fundo desfocado e escurecido, mas ainda preenchendo o topo e a base.
    assert column[100] < 240
    assert column[1820] < 240


# --- layout blurred_16_9 --------------------------------------------------


def test_sixteen_by_nine_layout_preserves_the_whole_frame() -> None:
    plan = plan_layout(1920, 1080, VerticalLayout.BLURRED_16_9)

    assert plan.layout is VerticalLayout.BLURRED_16_9
    # Sem crop lateral: o recorte é o frame inteiro.
    assert (plan.crop_width, plan.crop_height) == (1920, 1080)
    assert (plan.foreground_width, plan.foreground_height) == (1080, 608)


def test_sixteen_by_nine_layout_does_not_distort() -> None:
    plan = plan_layout(1920, 1080, VerticalLayout.BLURRED_16_9)
    assert plan.foreground_width is not None and plan.foreground_height is not None

    source_aspect = 1920 / 1080
    foreground_aspect = plan.foreground_width / plan.foreground_height
    assert abs(source_aspect - foreground_aspect) < 0.01


def test_vertical_source_ignores_the_horizontal_layouts() -> None:
    for layout in (VerticalLayout.BLURRED_4_3, VerticalLayout.BLURRED_16_9):
        plan = plan_layout(1080, 1920, layout)
        assert plan.layout is VerticalLayout.CENTER_CROP
        assert plan.uses_background is False


def test_render_uses_the_layout_stored_on_the_video(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    """O handler repassa `Video.layout`; nada de default global no pipeline."""
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        video.apply_settings(VideoSettings(layout=VerticalLayout.BLURRED_16_9))

    graphs: list[str] = []

    def _run(args: list[str], timeout: float) -> CommandResult:
        graphs.append(args[args.index("-filter_complex") + 1])
        Path(args[-1]).write_bytes(b"render")
        return CommandResult(0, "", "")

    monkeypatch.setattr("app.services.rendering.renderer.require_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.services.rendering.renderer.run_command", _run)
    monkeypatch.setattr("app.services.rendering.renderer.probe_file", lambda p, timeout: None)

    handle_render(context)

    # 1280x720 no layout 16:9: foreground 1080x608, sem crop lateral.
    assert "crop=1280:720,scale=1080:608" in graphs[0]


@requires_ffmpeg
@pytest.mark.parametrize(
    ("layout", "expected_band"),
    [(VerticalLayout.BLURRED_4_3, 810), (VerticalLayout.BLURRED_16_9, 608)],
)
def test_real_render_band_height_per_layout(
    settings: Settings, tmp_path: Path, layout: VerticalLayout, expected_band: int
) -> None:
    from PIL import Image

    settings.ensure_storage_dirs()
    source = tmp_path / f"{layout.value}.mp4"
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
            "color=c=white:size=1280x720:rate=25:duration=1",
            "-c:v",
            "libx264",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )

    output = tmp_path / f"out-{layout.value}.mp4"
    result = VerticalRenderer(settings).render(
        source, output, source_size=(1280, 720), settings=VideoSettings(layout=layout)
    )

    assert result.media_info is not None
    assert (result.media_info.width, result.media_info.height) == (1080, 1920)

    frame = tmp_path / f"frame-{layout.value}.png"
    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-y",
            str(frame),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )

    image = Image.open(frame).convert("L")
    column: list[int] = [int(image.getpixel((540, y))) for y in range(1920)]  # type: ignore[arg-type]
    bright = [y for y, value in enumerate(column) if value > 240]

    assert abs((bright[-1] - bright[0] + 1) - expected_band) <= 4
    assert abs(bright[0] - (1920 - expected_band) // 2) <= 4


def test_subtitles_use_the_font_size_stored_on_the_video(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    """O `.ass` de cada clip sai com o tamanho escolhido para aquele vídeo."""
    from app.services.subtitles.storage import SUBTITLES_SUBDIR

    _seed_transcript(context)
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        video.apply_settings(VideoSettings(subtitle_font_size=96))

    _fake_renderer(monkeypatch)
    handle_render(context)

    subtitle = context.settings.storage_path(SUBTITLES_SUBDIR) / context.video_id / "000.ass"
    assert "Style: bold,DejaVu Sans,96," in subtitle.read_text(encoding="utf-8")


# --- opções avançadas afetam o comando -----------------------------------


def _args_for(settings: VideoSettings) -> list[str]:
    return build_render_args(
        "/usr/bin/ffmpeg",
        Path("/in/source.mp4"),
        Path("/out/000.mp4"),
        plan=plan_layout(1920, 1080, settings.layout, foreground_scale=settings.foreground_scale),
        settings=settings,
    )


def test_blur_strength_changes_sigma_and_working_resolution() -> None:
    """A redução intermediária também borra, então ela acompanha a intensidade."""
    soft = _args_for(VideoSettings(blur_strength=0))[
        _args_for(VideoSettings(blur_strength=0)).index("-filter_complex") + 1
    ]
    strong = _args_for(VideoSettings(blur_strength=100))[
        _args_for(VideoSettings(blur_strength=100)).index("-filter_complex") + 1
    ]

    assert "gblur=sigma=4.0" in soft and "crop=540:960" in soft
    assert "gblur=sigma=26.0" in strong and "crop=216:384" in strong


def test_background_darkness_changes_the_brightness() -> None:
    graph = _args_for(VideoSettings(background_darkness=100))[
        _args_for(VideoSettings(background_darkness=100)).index("-filter_complex") + 1
    ]

    assert "eq=brightness=-0.35" in graph


def test_foreground_scale_shrinks_without_distorting() -> None:
    plan = plan_layout(1920, 1080, foreground_scale=70)
    assert plan.foreground_width is not None and plan.foreground_height is not None

    assert plan.foreground_width == 756
    # 4:3 preservado no recorte e na escala.
    assert abs(plan.foreground_width / plan.foreground_height - 4 / 3) < 0.01
    assert plan.foreground_width <= 1080 and plan.foreground_height <= 1920


def test_foreground_never_leaves_the_canvas() -> None:
    # Fonte muito alta com escala máxima: a altura é que limita.
    plan = plan_layout(1000, 1000, VerticalLayout.BLURRED_16_9, foreground_scale=100)
    assert plan.foreground_height is not None and plan.foreground_height <= 1920


@pytest.mark.parametrize(
    ("quality", "preset", "crf"),
    [("fast", "superfast", "24"), ("balanced", "veryfast", "21"), ("high", "slow", "18")],
)
def test_quality_maps_to_encoder_parameters(quality: str, preset: str, crf: str) -> None:
    args = _args_for(VideoSettings(render_quality=quality))

    assert args[args.index("-preset") + 1] == preset
    assert args[args.index("-crf") + 1] == crf


def test_fps_original_does_not_resample() -> None:
    graph = _args_for(VideoSettings())[_args_for(VideoSettings()).index("-filter_complex") + 1]

    assert "fps=" not in graph


@pytest.mark.parametrize("fps", ["30", "60"])
def test_forced_fps_enters_the_filtergraph(fps: str) -> None:
    args = _args_for(VideoSettings(output_fps=fps))
    graph = args[args.index("-filter_complex") + 1]

    assert f"fps={fps}" in graph


def test_volume_and_normalization_are_applied_in_order() -> None:
    args = _args_for(VideoSettings(volume=50, normalize_audio=True))
    audio = args[args.index("-af") + 1]

    # Normaliza e só então aplica o ganho; o contrário desfaria a escolha.
    assert audio.index("loudnorm") < audio.index("volume=0.50")


def test_no_audio_filter_when_nothing_changes() -> None:
    assert "-af" not in _args_for(VideoSettings())


def test_subtitles_disabled_never_reaches_the_filtergraph(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    """Legenda OFF: nenhum `.ass` é escrito e o filtro não entra no comando."""
    from app.services.subtitles.storage import SUBTITLES_SUBDIR

    _seed_transcript(context)
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        video.apply_settings(VideoSettings(clip_duration_seconds=30, subtitles_enabled=False))

    graphs: list[str] = []

    def _run(args: list[str], timeout: float) -> CommandResult:
        graphs.append(args[args.index("-filter_complex") + 1])
        Path(args[-1]).write_bytes(b"render")
        return CommandResult(0, "", "")

    monkeypatch.setattr("app.services.rendering.renderer.require_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.services.rendering.renderer.run_command", _run)
    monkeypatch.setattr("app.services.rendering.renderer.probe_file", lambda p, timeout: None)

    handle_render(context)

    assert graphs and all("subtitles=" not in graph for graph in graphs)
    assert not (context.settings.storage_path(SUBTITLES_SUBDIR) / context.video_id).exists()


@requires_ffmpeg
def test_real_render_with_advanced_settings(settings: Settings, tmp_path: Path) -> None:
    """Escala menor, blur forte, 30 FPS e volume reduzido, em um encode só."""
    settings.ensure_storage_dirs()
    source = tmp_path / "src.mp4"
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
            "color=c=white:size=1280x720:rate=25:duration=2",
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

    result = VerticalRenderer(settings).render(
        source,
        tmp_path / "out.mp4",
        source_size=(1280, 720),
        settings=VideoSettings(
            foreground_scale=70,
            blur_strength=90,
            background_darkness=80,
            output_fps="30",
            volume=50,
            render_quality="fast",
        ),
    )

    assert result.media_info is not None
    assert (result.media_info.width, result.media_info.height) == (1080, 1920)
    assert result.media_info.fps == 30.0
    assert result.media_info.audio_codec == "aac"

    from PIL import Image

    frame = tmp_path / "frame.png"
    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(tmp_path / "out.mp4"),
            "-frames:v",
            "1",
            "-y",
            str(frame),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    image = Image.open(frame).convert("L")
    column: list[int] = [int(image.getpixel((540, y))) for y in range(1920)]  # type: ignore[arg-type]
    bright = [y for y, value in enumerate(column) if value > 240]

    # 70% de 1080 em 4:3 -> faixa de ~566px, centralizada.
    assert abs((bright[-1] - bright[0] + 1) - 566) <= 6


def test_export_job_is_chained_only_when_a_folder_is_chosen(
    monkeypatch: pytest.MonkeyPatch, context: JobContext, tmp_path: Path
) -> None:
    from app.models.enums import JobType

    _fake_renderer(monkeypatch)
    handle_render(context)

    with session_scope(context.session_factory) as session:
        jobs = JobRepository(session).list_for_video(context.video_id)
        assert not [job for job in jobs if job.job_type is JobType.EXPORT]

        video = VideoRepository(session).get_by_id(context.video_id)
        assert video is not None
        video.apply_settings(
            VideoSettings(clip_duration_seconds=30, output_directory=str(tmp_path / "saida"))
        )

    handle_render(context)

    with session_scope(context.session_factory) as session:
        jobs = JobRepository(session).list_for_video(context.video_id)
        assert len([job for job in jobs if job.job_type is JobType.EXPORT]) == 1
