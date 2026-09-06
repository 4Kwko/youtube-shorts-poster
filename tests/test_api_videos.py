"""Testes da API de vídeos.

Nenhum download real: a criação só grava no banco, e o worker não roda aqui.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.constants import CLIP_DURATION_OPTIONS, MAX_BATCH_VIDEOS
from app.db.session import session_scope
from app.main import create_app
from app.models.enums import JobStatus, JobType, VerticalLayout, VideoStatus
from app.repositories import JobRepository, VideoRepository

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
def api_settings(settings: Settings, tmp_path: Path) -> Settings:
    database_url = f"sqlite:///{tmp_path / 'api.db'}"
    _run_migrations(database_url)
    return settings.model_copy(update={"database_url": database_url})


@pytest.fixture
def app(api_settings: Settings) -> FastAPI:
    return create_app(api_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(app: FastAPI) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = app.state.session_factory
    return factory


# --- POST /videos ---------------------------------------------------------


def test_create_video_returns_202(client: TestClient) -> None:
    response = client.post("/api/v1/videos", json={"url": VALID_URL})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == VideoStatus.QUEUED.value
    assert body["progress"] == 0
    assert body["provider"] == "youtube"
    assert body["current_stage"] == "queued"
    assert body["created_at"] and body["id"]


def test_create_video_persists_video_and_ingest_job(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]

    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(video_id)
        jobs = JobRepository(session).list_for_video(video_id)

        assert video is not None
        assert video.status is VideoStatus.QUEUED
        assert len(jobs) == 1
        assert jobs[0].job_type is JobType.INGEST
        assert jobs[0].status is JobStatus.QUEUED
        assert jobs[0].attempt == 0


def test_create_video_strips_playlist_params(client: TestClient) -> None:
    body = client.post("/api/v1/videos", json={"url": f"{VALID_URL}&list=PL123&index=2"}).json()

    assert "list=" not in body["source_url"]


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "não é url", "", "http://127.0.0.1/video"],
    ids=["file", "texto", "vazio", "ssrf"],
)
def test_invalid_url_is_rejected(client: TestClient, url: str) -> None:
    response = client.post("/api/v1/videos", json={"url": url})

    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"invalid_video_url", "unsupported_video_url"}


def test_unsupported_provider_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/videos", json={"url": "https://evil.com/v.mp4"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_video_url"


def test_malformed_body_uses_error_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/videos", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_job_failure_rolls_back_video(
    monkeypatch: pytest.MonkeyPatch, app: FastAPI, session_factory: sessionmaker[Session]
) -> None:
    """Video e Job compartilham a transação da requisição."""

    def _boom(self: Any, **kwargs: Any) -> Any:
        raise RuntimeError("falha ao criar job")

    monkeypatch.setattr(JobRepository, "create", _boom)

    # raise_server_exceptions=False exercita o handler global em vez de
    # propagar a exceção para o teste.
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = failing_client.post("/api/v1/videos", json={"url": VALID_URL})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    with session_scope(session_factory) as session:
        assert VideoRepository(session).list() == []


# --- GET /videos/{id} -----------------------------------------------------


def test_get_existing_video(client: TestClient) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]

    response = client.get(f"/api/v1/videos/{video_id}")

    assert response.status_code == 200
    assert response.json()["id"] == video_id


def test_get_unknown_video_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/videos/nao-existe")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_video_response_never_exposes_storage_paths(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(video_id)
        assert video is not None
        video.source_file_key = f"{video_id}/source.mp4"

    response = client.get(f"/api/v1/videos/{video_id}")

    assert "source_file_key" not in response.json()
    assert "source.mp4" not in response.text
    assert "/storage" not in response.text


# --- GET /videos/{id}/jobs ------------------------------------------------


def test_list_jobs_for_video(client: TestClient) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]

    response = client.get(f"/api/v1/videos/{video_id}/jobs")

    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == JobType.INGEST.value
    assert jobs[0]["attempt"] == 0
    assert jobs[0]["max_attempts"] >= 1
    assert jobs[0]["started_at"] is None


def test_jobs_are_ordered_by_creation(
    client: TestClient, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.base import utcnow

    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    fixed_time = utcnow()
    monkeypatch.setattr("app.repositories.job.utcnow", lambda: fixed_time)
    with session_scope(session_factory) as session:
        repo = JobRepository(session)
        repo.create(video_id=video_id, job_type=JobType.TRANSCRIBE)
        repo.create(video_id=video_id, job_type=JobType.RENDER)

    types = [job["job_type"] for job in client.get(f"/api/v1/videos/{video_id}/jobs").json()]

    assert types == [JobType.INGEST.value, JobType.TRANSCRIBE.value, JobType.RENDER.value]


def test_jobs_of_other_video_are_not_returned(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    first = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    second = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]

    jobs = client.get(f"/api/v1/videos/{first}/jobs").json()

    assert len(jobs) == 1
    assert client.get(f"/api/v1/videos/{second}/jobs").json()[0]["id"] != jobs[0]["id"]


def test_jobs_of_unknown_video_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/videos/nao-existe/jobs")

    assert response.status_code == 404


def test_timestamps_are_utc_with_offset(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """SQLite devolve datetime naive; a API sempre marca UTC."""
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    with session_scope(session_factory) as session:
        JobRepository(session).claim(JobRepository(session).list_for_video(video_id)[0].id)

    video = client.get(f"/api/v1/videos/{video_id}").json()
    job = client.get(f"/api/v1/videos/{video_id}/jobs").json()[0]

    for value in (video["created_at"], video["updated_at"], job["created_at"], job["started_at"]):
        assert value.endswith("Z"), value


# --- clips ----------------------------------------------------------------


def _add_clips(session_factory: sessionmaker[Session], video_id: str) -> None:
    from app.repositories import ClipRepository

    with session_scope(session_factory) as session:
        repo = ClipRepository(session)
        # Fora de ordem de propósito: a API é que garante a ordenação.
        repo.create(video_id=video_id, sequence=1, start_time=90, end_time=180)
        repo.create(video_id=video_id, sequence=0, start_time=0, end_time=90)


def test_list_clips_is_ordered_by_sequence(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    _add_clips(session_factory, video_id)

    clips = client.get(f"/api/v1/videos/{video_id}/clips").json()

    assert [clip["sequence"] for clip in clips] == [0, 1]
    assert clips[0]["start_time"] == 0.0
    assert clips[0]["duration"] == 90.0
    assert clips[0]["video_id"] == video_id
    assert clips[0]["status"] == "pending"


def test_list_clips_empty_before_clipping(client: TestClient) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]

    response = client.get(f"/api/v1/videos/{video_id}/clips")

    assert response.status_code == 200
    assert response.json() == []


def test_list_clips_unknown_video_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/videos/nao-existe/clips").status_code == 404


def test_get_clip(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    _add_clips(session_factory, video_id)
    clip_id = client.get(f"/api/v1/videos/{video_id}/clips").json()[0]["id"]

    response = client.get(f"/api/v1/clips/{clip_id}")

    assert response.status_code == 200
    assert response.json()["id"] == clip_id


def test_get_unknown_clip_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/clips/nao-existe")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_clip_response_hides_storage_keys(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.repositories import ClipRepository

    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    with session_scope(session_factory) as session:
        clip = ClipRepository(session).create(
            video_id=video_id,
            sequence=0,
            start_time=0,
            end_time=90,
            source_file_key=f"{video_id}/000.mp4",
        )
        clip.rendered_file_key = f"{video_id}/000-9x16.mp4"

    body = client.get(f"/api/v1/videos/{video_id}/clips").text

    assert "source_file_key" not in body
    assert "rendered_file_key" not in body
    assert "000.mp4" not in body


# --- transcript -----------------------------------------------------------


def test_get_transcript(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    from app.repositories import TranscriptRepository
    from app.schemas.transcript import TranscriptResult, TranscriptSegment, TranscriptWord
    from app.services.transcription import write_transcript

    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    result = TranscriptResult(
        language="pt",
        language_probability=0.98,
        duration=6.0,
        segments=[
            TranscriptSegment(
                start=0.0,
                end=3.2,
                text="Hoje é sobre atenção.",
                words=[TranscriptWord(start=0.1, end=0.5, word="Hoje")],
            )
        ],
    )
    settings = client.app.state.settings  # type: ignore[attr-defined]
    file_key = write_transcript(settings, video_id, result)
    with session_scope(session_factory) as session:
        TranscriptRepository(session).upsert(
            video_id=video_id, file_key=file_key, language="pt", language_probability=0.98
        )

    response = client.get(f"/api/v1/videos/{video_id}/transcript")

    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == video_id
    assert body["language"] == "pt"
    assert body["segments"][0]["text"] == "Hoje é sobre atenção."
    assert body["segments"][0]["words"][0]["word"] == "Hoje"
    assert "file_key" not in response.text
    assert "transcript.json" not in response.text


def test_get_transcript_before_transcription_returns_404(client: TestClient) -> None:
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]

    response = client.get(f"/api/v1/videos/{video_id}/transcript")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_transcript_unknown_video_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/videos/nao-existe/transcript").status_code == 404


# --- configurações de processamento ---------------------------------------


def test_create_uses_documented_defaults(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    settings = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["settings"]

    assert settings["version"] == 1
    assert settings["clip_duration_seconds"] == 90
    assert settings["layout"] == "blurred_4_3"
    assert settings["subtitles_enabled"] is True
    assert settings["subtitle_font_size"] == 72
    assert settings["render_quality"] == "balanced"
    assert settings["output_fps"] == "original"
    assert settings["volume"] == 100
    assert settings["normalize_audio"] is False

    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(
            client.get("/api/v1/videos/" + _first_video_id(client)).json()["id"]
        )
        assert video is not None
        assert video.settings.layout is VerticalLayout.BLURRED_4_3
        # Colunas legadas continuam espelhadas enquanto existirem.
        assert video.clip_duration_seconds == 90


def _first_video_id(client: TestClient) -> str:
    video_id: str = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]
    return video_id


@pytest.mark.parametrize("duration", CLIP_DURATION_OPTIONS)
def test_every_offered_duration_is_accepted(client: TestClient, duration: int) -> None:
    response = client.post(
        "/api/v1/videos",
        json={"url": VALID_URL, "settings": {"clip_duration_seconds": duration}},
    )

    assert response.status_code == 202
    assert response.json()["settings"]["clip_duration_seconds"] == duration


@pytest.mark.parametrize("duration", [0, -30, 45, 91, 501, 3600])
def test_duration_outside_the_list_is_rejected(client: TestClient, duration: int) -> None:
    response = client.post(
        "/api/v1/videos",
        json={"url": VALID_URL, "settings": {"clip_duration_seconds": duration}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("layout", ["center_crop", "blurred_4_3", "blurred_16_9"])
def test_every_supported_layout_is_accepted(client: TestClient, layout: str) -> None:
    response = client.post(
        "/api/v1/videos", json={"url": VALID_URL, "settings": {"layout": layout}}
    )

    assert response.status_code == 202
    assert response.json()["settings"]["layout"] == layout


@pytest.mark.parametrize(
    "payload",
    [
        {"layout": "fullscreen"},
        {"subtitle_font_size": 47},
        {"subtitle_font_size": 111},
        {"subtitle_position": "middle"},
        {"subtitle_vertical_offset": 900},
        {"subtitle_style": "karaoke"},
        {"subtitle_text_color": "branco"},
        {"subtitle_outline_color": "#GGGGGG"},
        {"blur_strength": 101},
        {"background_darkness": -1},
        {"foreground_scale": 10},
        {"foreground_scale": 140},
        {"render_quality": "ultra"},
        {"output_fps": "24"},
        {"volume": 200},
        {"desconhecido": 1},
    ],
)
def test_invalid_settings_are_rejected(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/api/v1/videos", json={"url": VALID_URL, "settings": payload})

    assert response.status_code == 422


@pytest.mark.parametrize("size", [48, 72, 90, 110])
def test_subtitle_size_inside_the_range_is_accepted(client: TestClient, size: int) -> None:
    response = client.post(
        "/api/v1/videos", json={"url": VALID_URL, "settings": {"subtitle_font_size": size}}
    )

    assert response.status_code == 202
    assert response.json()["settings"]["subtitle_font_size"] == size


def test_settings_are_persisted_per_video(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    first = client.post(
        "/api/v1/videos",
        json={
            "url": VALID_URL,
            "settings": {
                "clip_duration_seconds": 30,
                "layout": "blurred_16_9",
                "subtitle_font_size": 96,
                "subtitles_enabled": False,
                "blur_strength": 80,
                "volume": 60,
                "output_fps": "30",
            },
        },
    ).json()
    second = client.post("/api/v1/videos", json={"url": VALID_URL}).json()

    assert first["settings"]["blur_strength"] == 80
    assert first["settings"]["subtitles_enabled"] is False
    # O segundo vídeo não herda nada do primeiro.
    assert second["settings"] == {**second["settings"], "blur_strength": 40, "volume": 100}

    with session_scope(session_factory) as session:
        stored = VideoRepository(session).get_by_id(first["id"])
        assert stored is not None
        assert stored.settings.layout is VerticalLayout.BLURRED_16_9
        assert stored.settings.output_fps.value == "30"


def test_legacy_video_without_settings_json_falls_back_to_columns(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Registro anterior à coluna JSON: a configuração vem das colunas legadas."""
    video_id = client.post("/api/v1/videos", json={"url": VALID_URL}).json()["id"]

    with session_scope(session_factory) as session:
        video = VideoRepository(session).get_by_id(video_id)
        assert video is not None
        video.settings_json = None
        video.clip_duration_seconds = 150
        video.layout = VerticalLayout.CENTER_CROP
        video.subtitle_font_size = 100

    body = client.get(f"/api/v1/videos/{video_id}").json()

    assert body["settings"]["clip_duration_seconds"] == 150
    assert body["settings"]["layout"] == "center_crop"
    assert body["settings"]["subtitle_font_size"] == 100
    # O resto vem dos defaults, que reproduzem o comportamento antigo.
    assert body["settings"]["subtitles_enabled"] is True


# --- batch ----------------------------------------------------------------


def test_batch_creates_one_project_per_url(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    urls = [f"https://www.youtube.com/watch?v=abc{index}" for index in range(3)]

    response = client.post("/api/v1/videos/batch", json={"urls": urls})

    assert response.status_code == 202
    videos = response.json()["videos"]
    assert len(videos) == 3
    assert [video["source_url"] for video in videos] == urls
    assert all(video["status"] == "queued" for video in videos)

    with session_scope(session_factory) as session:
        for video in videos:
            jobs = JobRepository(session).list_for_video(video["id"])
            assert [job.job_type for job in jobs] == [JobType.INGEST]
            assert jobs[0].status is JobStatus.QUEUED


def test_batch_with_a_single_url_behaves_like_the_simple_post(client: TestClient) -> None:
    response = client.post("/api/v1/videos/batch", json={"urls": [VALID_URL]})

    assert response.status_code == 202
    assert len(response.json()["videos"]) == 1


def test_batch_gives_each_video_its_own_settings_snapshot(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    body = client.post(
        "/api/v1/videos/batch",
        json={
            "urls": [f"https://www.youtube.com/watch?v=abc{index}" for index in range(3)],
            "settings": {"clip_duration_seconds": 120, "layout": "blurred_16_9"},
        },
    ).json()

    with session_scope(session_factory) as session:
        for video in body["videos"]:
            stored = VideoRepository(session).get_by_id(video["id"])
            assert stored is not None
            assert stored.settings.clip_duration_seconds == 120
            assert stored.settings.layout is VerticalLayout.BLURRED_16_9


def test_batch_rejects_everything_when_one_url_is_invalid(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Nada é criado: metade dos projetos seria pior que nenhum."""
    response = client.post(
        "/api/v1/videos/batch",
        json={"urls": [VALID_URL, "file:///etc/passwd", VALID_URL]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_video_url"
    with session_scope(session_factory) as session:
        assert VideoRepository(session).list() == []


def test_batch_rejects_an_unsupported_provider(client: TestClient) -> None:
    response = client.post(
        "/api/v1/videos/batch", json={"urls": [VALID_URL, "https://evil.com/v.mp4"]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_video_url"


def test_batch_accepts_the_limit_and_refuses_one_more(client: TestClient) -> None:
    inside = [f"https://www.youtube.com/watch?v=v{index}" for index in range(MAX_BATCH_VIDEOS)]
    assert client.post("/api/v1/videos/batch", json={"urls": inside}).status_code == 202

    beyond = [*inside, "https://www.youtube.com/watch?v=extra"]
    response = client.post("/api/v1/videos/batch", json={"urls": beyond})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_batch_requires_at_least_one_url(client: TestClient) -> None:
    assert client.post("/api/v1/videos/batch", json={"urls": []}).status_code == 422


def test_batch_collapses_duplicates_within_the_request(client: TestClient) -> None:
    videos = client.post(
        "/api/v1/videos/batch",
        json={"urls": [VALID_URL, VALID_URL, f"{VALID_URL}&list=PL1"]},
    ).json()["videos"]

    # A limpeza dos parâmetros de playlist torna a terceira igual às anteriores.
    assert len(videos) == 1


def test_batch_keeps_insertion_order_for_the_queue(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    urls = [f"https://www.youtube.com/watch?v=ord{index}" for index in range(4)]

    created = client.post("/api/v1/videos/batch", json={"urls": urls}).json()["videos"]

    with session_scope(session_factory) as session:
        jobs = JobRepository(session).list_by_status(JobStatus.QUEUED)
        # O worker consome por created_at/id; a ordem da fila é a de inserção.
        assert [job.video_id for job in jobs] == [video["id"] for video in created]
