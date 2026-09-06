from __future__ import annotations

from typing import Any

import pytest

from app.schemas.media import MediaInfo
from app.services.ingest.metadata import (
    MAX_TITLE_LENGTH,
    build_source_info,
    extract_preflight,
    sanitize_title,
)


def _build(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "video_id": "a" * 32,
        "source_url": "https://www.youtube.com/watch?v=abc",
        "provider": "youtube",
        "local_filename": "source.mp4",
        "file_size_bytes": 1024,
        "info": {},
        "media_info": None,
    }
    kwargs.update(overrides)
    return build_source_info(**kwargs)


# --- sanitize_title -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Meu vídeo", "Meu vídeo"),
        ("  espaços  ", "espaços"),
        ("linha\nquebrada", "linhaquebrada"),
        ("nulo\x00byte", "nulobyte"),
        ("\x1b[31mescape", "[31mescape"),
        ("", None),
        ("   ", None),
        (None, None),
        (123, None),
        ({"a": 1}, None),
    ],
)
def test_sanitize_title(raw: Any, expected: str | None) -> None:
    assert sanitize_title(raw) == expected


def test_title_is_truncated() -> None:
    result = sanitize_title("x" * 5000)

    assert result is not None
    assert len(result) == MAX_TITLE_LENGTH


def test_malicious_title_never_reaches_filename() -> None:
    """O título é sanitizado para exibição e não participa do nome do arquivo."""
    info = _build(info={"title": "../../../etc/passwd\x00.mp4"}, local_filename="source.mp4")

    assert info.local_filename == "source.mp4"
    assert info.title is not None
    assert "\x00" not in info.title


# --- preflight ------------------------------------------------------------


def test_preflight_reads_known_fields() -> None:
    preflight = extract_preflight(
        {
            "id": "dQw4w9WgXcQ",
            "title": "Exemplo",
            "duration": 212.0,
            "height": 1080,
            "filesize": 5000,
            "is_live": False,
        }
    )

    assert preflight.provider_video_id == "dQw4w9WgXcQ"
    assert preflight.duration_seconds == 212.0
    assert preflight.height == 1080
    assert preflight.estimated_size_bytes == 5000
    assert preflight.is_live is False


def test_preflight_falls_back_to_approximate_size() -> None:
    preflight = extract_preflight({"filesize": None, "filesize_approx": 777})

    assert preflight.estimated_size_bytes == 777


def test_preflight_detects_live_status() -> None:
    assert extract_preflight({"live_status": "is_live"}).is_live is True
    assert extract_preflight({"is_live": True}).is_live is True


@pytest.mark.parametrize("payload", [None, [], "texto", 42])
def test_preflight_tolerates_garbage(payload: Any) -> None:
    preflight = extract_preflight(payload)

    assert preflight.duration_seconds is None
    assert preflight.is_live is False


# --- build_source_info ----------------------------------------------------


def test_incomplete_metadata_yields_none_fields() -> None:
    info = _build(info={"id": "abc"})

    assert info.title is None
    assert info.duration_seconds is None
    assert info.width is None
    assert info.fps is None
    assert info.video_codec is None
    assert info.provider_video_id == "abc"
    assert info.file_size_bytes == 1024


def test_ffprobe_takes_precedence_over_provider_metadata() -> None:
    info = _build(
        info={"width": 1920, "height": 1080, "fps": 30, "vcodec": "vp9", "ext": "webm"},
        media_info=MediaInfo(
            width=1080, height=1920, fps=59.94, video_codec="h264", container="mov,mp4"
        ),
    )

    assert (info.width, info.height) == (1080, 1920)
    assert info.fps == 59.94
    assert info.video_codec == "h264"
    assert info.container == "mov,mp4"


def test_provider_metadata_fills_gaps_left_by_ffprobe() -> None:
    info = _build(
        info={"width": 1280, "height": 720, "acodec": "opus", "duration": 90.0},
        media_info=MediaInfo(video_codec="vp9"),
    )

    assert info.width == 1280
    assert info.audio_codec == "opus"
    assert info.duration_seconds == 90.0
    assert info.video_codec == "vp9"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("avc1.640028", "avc1"), ("none", None), ("", None), ("unknown", None), ("AAC", "aac")],
)
def test_codec_normalization(raw: str, expected: str | None) -> None:
    info = _build(info={"vcodec": raw})

    assert info.video_codec == expected


def test_invalid_numeric_metadata_is_dropped() -> None:
    info = _build(info={"duration": "N/A", "width": -5, "height": 0, "fps": "abc"})

    assert info.duration_seconds is None
    assert info.width is None
    assert info.height is None
    assert info.fps is None


def test_source_info_never_carries_absolute_path() -> None:
    info = _build(local_filename="source.mkv")

    serialized = info.model_dump()
    assert serialized["local_filename"] == "source.mkv"
    strings = [value for value in serialized.values() if isinstance(value, str)]
    assert not any(value.startswith("/") for value in strings)
