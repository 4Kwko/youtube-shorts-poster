from __future__ import annotations

from typing import Any

import pytest

from app.services.media.errors import MediaProbeError
from app.services.media.probe import parse_probe_payload


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {
            "duration": "125.5",
            "bit_rate": "2500000",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        },
    }
    base.update(overrides)
    return base


def test_parses_full_metadata() -> None:
    info = parse_probe_payload(_payload())

    assert info.duration_seconds == 125.5
    assert info.width == 1920
    assert info.height == 1080
    assert info.fps == 29.97
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert info.bitrate_bps == 2500000
    assert info.container == "mov,mp4,m4a,3gp,3g2,mj2"
    assert info.has_video and info.has_audio
    assert info.is_vertical is False


def test_detects_vertical_video() -> None:
    payload = _payload()
    payload["streams"][0].update({"width": 1080, "height": 1920})

    info = parse_probe_payload(payload)

    assert info.is_vertical is True


def test_audio_only_file() -> None:
    payload = _payload(streams=[{"codec_type": "audio", "codec_name": "mp3", "duration": "10.0"}])
    payload["format"].pop("duration")

    info = parse_probe_payload(payload)

    assert info.has_video is False
    assert info.audio_codec == "mp3"
    assert info.duration_seconds == 10.0
    assert info.width is None
    assert info.fps is None


def test_video_without_audio_track() -> None:
    payload = _payload(streams=[_payload()["streams"][0]])

    info = parse_probe_payload(payload)

    assert info.has_audio is False
    assert info.audio_codec is None


def test_falls_back_to_r_frame_rate_when_avg_is_zero() -> None:
    payload = _payload()
    payload["streams"][0]["avg_frame_rate"] = "0/0"

    info = parse_probe_payload(payload)

    assert info.fps == 30.0


def test_missing_optional_fields_become_none() -> None:
    payload = _payload(
        streams=[{"codec_type": "video", "codec_name": "vp9"}],
        format={"format_name": "matroska,webm"},
    )

    info = parse_probe_payload(payload)

    assert info.duration_seconds is None
    assert info.bitrate_bps is None
    assert info.width is None
    assert info.fps is None
    assert info.container == "matroska,webm"


@pytest.mark.parametrize(
    "bad_value",
    ["N/A", "", None, "abc", "-1", 0],
    ids=["na", "empty", "none", "text", "negative", "zero"],
)
def test_unparseable_numeric_values_become_none(bad_value: Any) -> None:
    payload = _payload()
    payload["format"]["duration"] = bad_value
    payload["format"]["bit_rate"] = bad_value
    payload["streams"][0].pop("duration", None)
    payload["streams"][1].pop("duration", None)

    info = parse_probe_payload(payload)

    assert info.duration_seconds is None
    assert info.bitrate_bps is None


@pytest.mark.parametrize("payload", [None, [], "texto", 42], ids=["none", "list", "str", "int"])
def test_non_dict_payload_raises(payload: Any) -> None:
    with pytest.raises(MediaProbeError):
        parse_probe_payload(payload)


def test_payload_without_usable_streams_raises() -> None:
    with pytest.raises(MediaProbeError, match="faixas de áudio ou vídeo"):
        parse_probe_payload({"streams": [], "format": {"format_name": "data"}})


def test_ignores_non_av_streams() -> None:
    payload = _payload()
    payload["streams"].insert(0, {"codec_type": "subtitle", "codec_name": "mov_text"})

    info = parse_probe_payload(payload)

    assert info.video_codec == "h264"
