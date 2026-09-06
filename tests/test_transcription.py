"""Testes da transcrição.

O backend do faster-whisper é sempre substituído: nenhum modelo é baixado e
nenhum teste usa rede.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.jobs import handlers as handlers_module
from app.jobs.context import JobContext
from app.jobs.handlers import handle_transcribe
from app.models.enums import JobStatus, JobType, VideoStatus
from app.models.transcript import Transcript
from app.repositories import JobRepository, TranscriptRepository, VideoRepository
from app.schemas.settings import VideoSettings
from app.schemas.transcript import TranscriptResult
from app.services.ingest.service import DOWNLOADS_SUBDIR
from app.services.transcription import (
    normalize_segments,
    read_transcript,
    reset_model_cache,
    transcript_file_key,
    write_transcript,
)
from app.services.transcription.backend import load_model, transcribe_file
from app.services.transcription.errors import (
    TranscriptionFailedError,
    TranscriptionModelUnavailableError,
    TranscriptUnavailableError,
)
from app.services.transcription.storage import TRANSCRIPTS_SUBDIR

# --- duplos do faster-whisper --------------------------------------------


@dataclass
class FakeWord:
    start: float
    end: float
    word: str


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str
    words: list[FakeWord] | None = None


@dataclass
class FakeInfo:
    language: str = "pt"
    language_probability: float = 0.98
    duration: float = 6.0


PT_SEGMENTS = [
    FakeSegment(
        start=0.0,
        end=3.2,
        text=" Hoje é sobre atenção. ",
        words=[
            FakeWord(0.1, 0.5, " Hoje"),
            FakeWord(0.5, 0.7, " é"),
            FakeWord(0.7, 1.2, " sobre"),
            FakeWord(1.2, 2.0, " atenção."),
        ],
    ),
    FakeSegment(
        start=3.2,
        end=6.0,
        text="Não é coincidência.",
        words=[FakeWord(3.3, 3.6, "Não"), FakeWord(3.6, 5.9, "coincidência.")],
    ),
]


class FakeModel:
    def __init__(self, segments: list[FakeSegment] | None = None) -> None:
        self.segments = segments if segments is not None else PT_SEGMENTS
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: str, **kwargs: Any) -> tuple[Any, Any]:
        self.calls.append({"audio": audio, **kwargs})
        return iter(self.segments), FakeInfo()


@pytest.fixture(autouse=True)
def _clean_model_cache() -> Iterator[None]:
    reset_model_cache()
    yield
    reset_model_cache()


# --- normalização ---------------------------------------------------------


def test_normalizes_segments_and_word_timestamps() -> None:
    segments = normalize_segments(PT_SEGMENTS)

    assert len(segments) == 2
    assert segments[0].start == 0.0
    assert segments[0].end == 3.2
    # Texto e palavras chegam do Whisper com espaço à esquerda.
    assert segments[0].text == "Hoje é sobre atenção."
    assert [word.word for word in segments[0].words] == ["Hoje", "é", "sobre", "atenção."]
    assert segments[0].words[0].start == 0.1
    assert segments[0].words[-1].end == 2.0


def test_preserves_unicode_and_accents() -> None:
    segments = normalize_segments(PT_SEGMENTS)

    assert "atenção" in segments[0].text
    assert "coincidência." in [word.word for word in segments[1].words]


def test_timestamps_stay_on_the_original_video_axis() -> None:
    """Segundo segmento continua em 3.2s, não rebaseado para zero."""
    segments = normalize_segments(PT_SEGMENTS)

    assert segments[1].start == 3.2
    assert segments[1].words[0].start == 3.3


def test_segments_without_usable_timestamps_are_dropped() -> None:
    segments = normalize_segments(
        [
            FakeSegment(start=None, end=1.0, text="sem início"),  # type: ignore[arg-type]
            FakeSegment(start=0.0, end=1.0, text="válido", words=None),
            FakeSegment(
                start=1.0,
                end=2.0,
                text="palavra ruim",
                words=[FakeWord(None, 2.0, "x")],  # type: ignore[arg-type]
            ),
        ]
    )

    assert [segment.text for segment in segments] == ["válido", "palavra ruim"]
    assert segments[1].words == []


def test_transcribe_requests_word_timestamps(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    model = FakeModel()
    monkeypatch.setattr("app.services.transcription.backend.load_model", lambda s: model)

    result = transcribe_file(settings, tmp_path / "source.mp4")

    assert model.calls[0]["word_timestamps"] is True
    assert result.language == "pt"
    assert result.language_probability == 0.98
    assert result.version == 1


def test_backend_failure_becomes_transcription_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    class BrokenModel:
        def transcribe(self, audio: str, **kwargs: Any) -> tuple[Any, Any]:
            raise RuntimeError("/opt/modelos/pt.bin corrompido")

    monkeypatch.setattr("app.services.transcription.backend.load_model", lambda s: BrokenModel())

    with pytest.raises(TranscriptionFailedError) as exc:
        transcribe_file(settings, tmp_path / "source.mp4")

    assert "/opt/modelos" not in exc.value.message


def test_missing_library_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """Sem faster-whisper instalado, o erro é de transcrição — não quebra o import."""
    import builtins

    real_import = builtins.__import__

    def _no_whisper(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "faster_whisper":
            raise ImportError("No module named 'faster_whisper'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_whisper)

    with pytest.raises(TranscriptionModelUnavailableError):
        load_model(settings)


def test_model_is_loaded_once_and_reused(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    loads: list[str] = []

    class FakeWhisperModel:
        def __init__(self, model: str, **kwargs: Any) -> None:
            loads.append(model)

        def transcribe(self, audio: str, **kwargs: Any) -> tuple[Any, Any]:
            return iter([]), FakeInfo()

    module = type("mod", (), {"WhisperModel": FakeWhisperModel})
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", module)

    load_model(settings)
    load_model(settings)

    assert len(loads) == 1


# --- persistência do JSON -------------------------------------------------


def test_transcript_json_roundtrip(settings: Settings) -> None:
    settings.ensure_storage_dirs()
    result = TranscriptResult(
        language="pt", language_probability=0.9, segments=normalize_segments(PT_SEGMENTS)
    )

    file_key = write_transcript(settings, "video123", result)
    loaded = read_transcript(settings, file_key)

    assert file_key == "video123/transcript.json"
    assert not file_key.startswith("/")
    assert loaded.segments[0].text == "Hoje é sobre atenção."
    assert loaded.version == 1


def test_transcript_json_is_utf8_with_accents(settings: Settings) -> None:
    settings.ensure_storage_dirs()
    write_transcript(
        settings, "video123", TranscriptResult(segments=normalize_segments(PT_SEGMENTS))
    )

    path = settings.storage_path(TRANSCRIPTS_SUBDIR) / "video123" / "transcript.json"
    raw = path.read_text(encoding="utf-8")

    assert "atenção" in raw
    assert "\\u00e7" not in raw
    assert json.loads(raw)["version"] == 1


def test_reading_missing_transcript_raises(settings: Settings) -> None:
    settings.ensure_storage_dirs()

    with pytest.raises(TranscriptUnavailableError):
        read_transcript(settings, transcript_file_key("ausente"))


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
def transcribe_settings(settings: Settings, tmp_path: Path) -> Settings:
    updated = settings.model_copy(
        update={"database_url": f"sqlite:///{tmp_path / 'transcribe.db'}"}
    )
    updated.ensure_storage_dirs()
    return updated


@pytest.fixture
def engine(transcribe_settings: Settings) -> Iterator[Engine]:
    _run_migrations(transcribe_settings.database_url)
    engine = create_db_engine(transcribe_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def context(transcribe_settings: Settings, session_factory: sessionmaker[Session]) -> JobContext:
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url="https://www.youtube.com/watch?v=abc123",
            provider="youtube",
            status=VideoStatus.DOWNLOADED,
        )
        video.duration = 6.0
        video.source_file_key = f"{video.id}/source.mp4"
        job = JobRepository(session).create(video_id=video.id, job_type=JobType.TRANSCRIBE)
        video_id, job_id = video.id, job.id

    source_dir = transcribe_settings.storage_path(DOWNLOADS_SUBDIR) / video_id
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source.mp4").write_bytes(b"video original")

    return JobContext(
        settings=transcribe_settings,
        session_factory=session_factory,
        job_id=job_id,
        video_id=video_id,
        job_type=JobType.TRANSCRIBE,
    )


def _fake_transcribe(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    seen: list[Path] = []

    def _transcribe(settings: Settings, source: Path) -> TranscriptResult:
        seen.append(source)
        return TranscriptResult(
            language="pt",
            language_probability=0.98,
            duration=6.0,
            segments=normalize_segments(PT_SEGMENTS),
        )

    monkeypatch.setattr(handlers_module, "transcribe_file", _transcribe)
    return seen


def test_handler_transcribes_original_and_persists(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    seen = _fake_transcribe(monkeypatch)

    handle_transcribe(context)

    assert seen[0].name == "source.mp4"
    with session_scope(context.session_factory) as session:
        transcript = TranscriptRepository(session).get_for_video(context.video_id)
        video = VideoRepository(session).get_by_id(context.video_id)

        assert transcript is not None
        assert transcript.language == "pt"
        assert transcript.language_probability == 0.98
        assert transcript.file_key == f"{context.video_id}/transcript.json"
        assert video is not None
        assert video.status is VideoStatus.TRANSCRIBED
        assert video.progress == 100

    stored = read_transcript(context.settings, f"{context.video_id}/transcript.json")
    assert len(stored.segments) == 2


def test_transcribe_enqueues_clip_job(monkeypatch: pytest.MonkeyPatch, context: JobContext) -> None:
    _fake_transcribe(monkeypatch)

    handle_transcribe(context)

    with session_scope(context.session_factory) as session:
        jobs = JobRepository(session).list_for_video(context.video_id)
        clip_jobs = [job for job in jobs if job.job_type is JobType.CLIP]

    assert len(clip_jobs) == 1
    assert clip_jobs[0].status is JobStatus.QUEUED


def test_retry_does_not_duplicate_transcript_or_clip_job(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    _fake_transcribe(monkeypatch)

    handle_transcribe(context)
    handle_transcribe(context)

    with session_scope(context.session_factory) as session:
        transcripts = session.query(Transcript).filter_by(video_id=context.video_id).all()
        jobs = JobRepository(session).list_for_video(context.video_id)

    assert len(transcripts) == 1
    assert len([job for job in jobs if job.job_type is JobType.CLIP]) == 1


def test_failure_removes_partial_json_and_skips_clip_job(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    def _boom(settings: Settings, source: Path) -> TranscriptResult:
        # Simula uma escrita parcial antes da falha.
        write_transcript(settings, context.video_id, TranscriptResult(segments=[]))
        raise TranscriptionFailedError("Falha ao transcrever o áudio do vídeo.")

    monkeypatch.setattr(handlers_module, "transcribe_file", _boom)

    with pytest.raises(TranscriptionFailedError):
        handle_transcribe(context)

    path = context.settings.storage_path(TRANSCRIPTS_SUBDIR) / context.video_id / "transcript.json"
    assert not path.exists()
    with session_scope(context.session_factory) as session:
        assert TranscriptRepository(session).get_for_video(context.video_id) is None
        jobs = JobRepository(session).list_for_video(context.video_id)
        assert not [job for job in jobs if job.job_type is JobType.CLIP]


def test_transcript_is_one_to_one_with_video(
    monkeypatch: pytest.MonkeyPatch, context: JobContext
) -> None:
    _fake_transcribe(monkeypatch)
    handle_transcribe(context)

    # session_scope faz rollback ao propagar; a sessão é aberta direto para
    # que o teste veja o IntegrityError e não o PendingRollbackError do commit.
    session = context.session_factory()
    try:
        session.add(Transcript(video_id=context.video_id, file_key="outro/transcript.json"))
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()


def test_transcribe_job_type_is_dispatched() -> None:
    assert handlers_module.HANDLERS[JobType.TRANSCRIBE] is handle_transcribe


def test_full_pipeline_chains_ingest_transcribe_clip_render(
    monkeypatch: pytest.MonkeyPatch,
    transcribe_settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    """Cadeia completa pelo worker, com download, Whisper e render mockados."""
    from app.jobs.queue import InMemoryJobQueue
    from app.jobs.worker import Worker
    from app.repositories import ClipRepository
    from app.schemas.ingest import VideoSourceInfo
    from app.services.rendering import VerticalRenderer

    settings = transcribe_settings

    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url="https://www.youtube.com/watch?v=abc123",
            provider="youtube",
            status=VideoStatus.QUEUED,
        )
        video.apply_settings(VideoSettings(clip_duration_seconds=30))
        JobRepository(session).create(video_id=video.id, job_type=JobType.INGEST)
        video_id = video.id

    source_dir = settings.storage_path(DOWNLOADS_SUBDIR) / video_id
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source.mp4").write_bytes(b"video original")

    def _import(settings_: Settings, url: str, **kwargs: Any) -> VideoSourceInfo:
        return VideoSourceInfo(
            id=video_id,
            source_url=url,
            provider="youtube",
            duration_seconds=6.0,
            local_filename="source.mp4",
            file_size_bytes=1024,
        )

    monkeypatch.setattr(handlers_module, "import_video", _import)
    _fake_transcribe(monkeypatch)
    monkeypatch.setattr(VerticalRenderer, "__init__", lambda self, s: None)
    monkeypatch.setattr(
        VerticalRenderer,
        "render",
        lambda self, source, output, **kwargs: (
            output.parent.mkdir(parents=True, exist_ok=True),
            output.write_bytes(b"render"),
        )[0],
    )

    worker = Worker(settings, session_factory, InMemoryJobQueue())
    for _ in range(4):
        worker.recover()
        worker.process_one()

    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_for_video(video_id)
        clips = ClipRepository(session).list_for_video(video_id)
        final = VideoRepository(session).get_by_id(video_id)

        assert [job.job_type for job in jobs] == [
            JobType.INGEST,
            JobType.TRANSCRIBE,
            JobType.CLIP,
            JobType.RENDER,
        ]
        assert all(job.status is JobStatus.SUCCEEDED for job in jobs)
        assert len(clips) == 1
        assert all(clip.rendered_file_key is not None for clip in clips)
        assert final is not None
        assert final.status is VideoStatus.RENDERED
        assert TranscriptRepository(session).get_for_video(video_id) is not None


# --- compatibilidade com a biblioteca real --------------------------------


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("faster_whisper") is None,
    reason="faster-whisper não instalado",
)
def test_normalization_matches_installed_faster_whisper_types() -> None:
    """Valida a forma da API real sem baixar modelo.

    Constrói `Segment`/`Word` da própria biblioteca instalada: se uma versão
    futura renomear campos, este teste quebra antes da produção.
    """
    from faster_whisper.transcribe import Segment, Word

    word = Word(start=0.1, end=0.5, word=" Atenção", probability=0.9)
    segment = Segment(
        id=1,
        seek=0,
        start=0.0,
        end=1.0,
        text=" Atenção total. ",
        tokens=[],
        avg_logprob=-0.1,
        compression_ratio=1.0,
        no_speech_prob=0.01,
        words=[word],
        temperature=0.0,
    )

    segments = normalize_segments([segment])

    assert segments[0].text == "Atenção total."
    assert segments[0].words[0].word == "Atenção"
    assert segments[0].words[0].start == 0.1
