"""Testes de reprodução e download dos renders."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import session_scope
from app.main import create_app
from app.models.enums import ClipStatus, VideoStatus
from app.repositories import ClipRepository, VideoRepository
from app.services.rendering import RENDERS_SUBDIR
from app.utils.ranges import RangeNotSatisfiableError, parse_range_header

CONTENT = bytes(range(256)) * 8  # 2048 bytes determinísticos
VALID_URL = "https://www.youtube.com/watch?v=abc123"


# --- parser de Range (função pura) ---------------------------------------


def test_absent_or_malformed_range_is_ignored() -> None:
    for header in (None, "", "items=0-10", "bytes=abc", "bytes=1-2, 5-6", "bytes=-"):
        assert parse_range_header(header, 1000) is None


def test_open_ended_range() -> None:
    byte_range = parse_range_header("bytes=0-", 1000)

    assert byte_range is not None
    assert (byte_range.start, byte_range.end, byte_range.length) == (0, 999, 1000)


def test_closed_range() -> None:
    byte_range = parse_range_header("bytes=1000-2000", 5000)

    assert byte_range is not None
    assert (byte_range.start, byte_range.end, byte_range.length) == (1000, 2000, 1001)


def test_suffix_range() -> None:
    byte_range = parse_range_header("bytes=-500", 2000)

    assert byte_range is not None
    assert (byte_range.start, byte_range.end) == (1500, 1999)


def test_suffix_larger_than_file_returns_whole_file() -> None:
    byte_range = parse_range_header("bytes=-9999", 100)

    assert byte_range is not None
    assert (byte_range.start, byte_range.end) == (0, 99)


def test_end_beyond_eof_is_clamped() -> None:
    byte_range = parse_range_header("bytes=100-999999", 500)

    assert byte_range is not None
    assert byte_range.end == 499


@pytest.mark.parametrize("header", ["bytes=500-", "bytes=1000-2000", "bytes=-0", "bytes=300-100"])
def test_unsatisfiable_ranges_raise(header: str) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_range_header(header, 500)


def test_content_range_header_format() -> None:
    byte_range = parse_range_header("bytes=10-19", 100)

    assert byte_range is not None
    assert byte_range.content_range(100) == "bytes 10-19/100"


# --- fixtures HTTP --------------------------------------------------------


def _run_migrations(database_url: str) -> None:
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture
def media_settings(settings: Settings, tmp_path: Path) -> Settings:
    database_url = f"sqlite:///{tmp_path / 'media.db'}"
    _run_migrations(database_url)
    updated = settings.model_copy(update={"database_url": database_url})
    updated.ensure_storage_dirs()
    return updated


@pytest.fixture
def app(media_settings: Settings) -> FastAPI:
    return create_app(media_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(app: FastAPI) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = app.state.session_factory
    return factory


def _make_clip(
    settings: Settings,
    session_factory: sessionmaker[Session],
    *,
    status: ClipStatus = ClipStatus.RENDERED,
    write_file: bool = True,
) -> str:
    with session_scope(session_factory) as session:
        video = VideoRepository(session).create(
            source_url=VALID_URL, provider="youtube", status=VideoStatus.RENDERED
        )
        clip = ClipRepository(session).create(
            video_id=video.id, sequence=1, start_time=90, end_time=180
        )
        if status is ClipStatus.RENDERED:
            clip.status = ClipStatus.RENDERED
            clip.rendered_file_key = f"{video.id}/001.mp4"
        else:
            clip.status = status
        clip_id, video_id = clip.id, video.id

    if write_file:
        directory = settings.storage_path(RENDERS_SUBDIR) / video_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "001.mp4").write_bytes(CONTENT)

    return clip_id


# --- GET /media -----------------------------------------------------------


def test_media_returns_whole_file(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/media")

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(CONTENT))
    assert "content-range" not in response.headers


def test_media_of_unknown_clip_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/clips/nao-existe/media")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_media_before_render_is_rejected(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory, status=ClipStatus.PENDING)

    response = client.get(f"/api/v1/clips/{clip_id}/media")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "clip_not_rendered"


def test_media_with_missing_file_is_reported(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory, write_file=False)

    response = client.get(f"/api/v1/clips/{clip_id}/media")

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "clip_media_missing"


def test_media_open_ended_range(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/media", headers={"Range": "bytes=0-"})

    assert response.status_code == 206
    assert response.content == CONTENT
    assert response.headers["content-range"] == f"bytes 0-{len(CONTENT) - 1}/{len(CONTENT)}"


def test_media_middle_range(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/media", headers={"Range": "bytes=1000-2000"})

    assert response.status_code == 206
    assert response.content == CONTENT[1000:2001]
    assert response.headers["content-range"] == f"bytes 1000-2000/{len(CONTENT)}"
    assert response.headers["content-length"] == "1001"


def test_media_suffix_range(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/media", headers={"Range": "bytes=-500"})

    assert response.status_code == 206
    assert response.content == CONTENT[-500:]
    assert response.headers["content-length"] == "500"


def test_media_range_beyond_eof_returns_416(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(
        f"/api/v1/clips/{clip_id}/media", headers={"Range": "bytes=999999-1000000"}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(CONTENT)}"
    assert response.json()["error"]["code"] == "range_not_satisfiable"


def test_media_malformed_range_falls_back_to_200(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/media", headers={"Range": "bytes=abc"})

    assert response.status_code == 200
    assert response.content == CONTENT


def test_media_range_end_beyond_eof_is_clamped(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/media", headers={"Range": "bytes=2040-999999"})

    assert response.status_code == 206
    assert response.content == CONTENT[2040:]


# --- GET /download --------------------------------------------------------


def test_download_uses_attachment_and_safe_filename(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/download")

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-disposition"] == 'attachment; filename="clip-001.mp4"'


def test_download_filename_ignores_external_text(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    """O nome vem só do `sequence` — título do provedor nunca entra no path."""
    clip_id = _make_clip(media_settings, session_factory)
    with session_scope(session_factory) as session:
        clip = ClipRepository(session).get_by_id(clip_id)
        assert clip is not None
        video = VideoRepository(session).get_by_id(clip.video_id)
        assert video is not None
        video.title = '../../etc/passwd "; rm -rf /'

    disposition = client.get(f"/api/v1/clips/{clip_id}/download").headers["content-disposition"]

    assert disposition == 'attachment; filename="clip-001.mp4"'
    assert ".." not in disposition


def test_download_supports_range(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory)

    response = client.get(f"/api/v1/clips/{clip_id}/download", headers={"Range": "bytes=0-99"})

    assert response.status_code == 206
    assert response.content == CONTENT[:100]


# --- vazamento de caminho -------------------------------------------------


def test_no_internal_path_is_exposed(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    clip_id = _make_clip(media_settings, session_factory, write_file=False)
    storage_root = str(media_settings.storage_root)

    responses = [
        client.get(f"/api/v1/clips/{clip_id}"),
        client.get(f"/api/v1/clips/{clip_id}/media"),
        client.get("/api/v1/clips/nao-existe/media"),
    ]

    for response in responses:
        assert storage_root not in response.text
        assert "rendered_file_key" not in response.text
        assert "source_file_key" not in response.text
        for header in response.headers.values():
            assert storage_root not in header


def test_clip_response_exposes_urls_only_when_rendered(
    client: TestClient, media_settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    rendered = _make_clip(media_settings, session_factory)
    pending = _make_clip(media_settings, session_factory, status=ClipStatus.PENDING)

    body = client.get(f"/api/v1/clips/{rendered}").json()
    assert body["media_url"] == f"/api/v1/clips/{rendered}/media"
    assert body["download_url"] == f"/api/v1/clips/{rendered}/download"

    assert client.get(f"/api/v1/clips/{pending}").json()["media_url"] is None
