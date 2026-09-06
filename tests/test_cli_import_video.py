from __future__ import annotations

from typing import Any

import pytest

from app.cli.import_video import main, render_summary
from app.core import config as config_module
from app.core.config import Settings
from app.schemas.ingest import VideoSourceInfo
from app.services.ingest import service as service_module
from app.services.ingest.errors import VideoUnavailableError

SAMPLE = VideoSourceInfo(
    id="0123456789abcdef0123456789abcdef",
    source_url="https://www.youtube.com/watch?v=abc",
    provider="youtube",
    provider_video_id="abc",
    title="Exemplo",
    duration_seconds=125.0,
    width=1920,
    height=1080,
    fps=30.0,
    video_codec="h264",
    audio_codec="aac",
    container="mov,mp4",
    file_size_bytes=5 * 1024 * 1024,
    local_filename="source.mp4",
)


@pytest.fixture(autouse=True)
def _cli_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    monkeypatch.setattr("app.cli.import_video.get_settings", lambda: settings)


def test_summary_contains_key_fields() -> None:
    output = render_summary(SAMPLE)

    assert SAMPLE.id in output
    assert "youtube" in output
    assert "00:02:05" in output
    assert "1920x1080" in output
    assert "5.0 MB" in output


def test_summary_never_prints_absolute_path() -> None:
    output = render_summary(SAMPLE)

    assert "/mnt/" not in output
    assert "/home/" not in output
    assert not any(line.split(":", 1)[-1].strip().startswith("/") for line in output.splitlines())
    assert f"downloads/{SAMPLE.id}/source.mp4" in output


def test_summary_handles_missing_metadata() -> None:
    minimal = VideoSourceInfo(
        id="f" * 32,
        source_url="https://vimeo.com/1",
        provider="vimeo",
        local_filename="source.mkv",
    )

    output = render_summary(minimal)

    assert "desconhecida" in output
    assert "desconhecido" in output


def test_main_prints_summary_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.cli.import_video.import_video", lambda *a, **k: SAMPLE)

    exit_code = main(["https://www.youtube.com/watch?v=abc"])

    assert exit_code == 0
    assert SAMPLE.id in capsys.readouterr().out


def test_main_rejects_invalid_url(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["file:///etc/passwd"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "invalid_video_url" in captured.err
    assert captured.out == ""


def test_main_reports_unavailable_video(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _fail(*args: Any, **kwargs: Any) -> None:
        raise VideoUnavailableError("O vídeo não está disponível para download.")

    monkeypatch.setattr("app.cli.import_video.import_video", _fail)

    exit_code = main(["https://www.youtube.com/watch?v=abc"])

    assert exit_code == 2
    assert "video_unavailable" in capsys.readouterr().err


def test_check_only_does_not_download(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = False

    def _should_not_run(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(service_module, "import_video", _should_not_run)

    exit_code = main(["--check-only", "https://www.youtube.com/watch?v=abc&list=PL1"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert called is False
    assert "youtube" in captured.out
    assert "playlist" in captured.out.lower()
