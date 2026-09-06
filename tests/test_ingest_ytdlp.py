"""Testes do adaptador do yt-dlp.

A biblioteca é substituída por um duplo: nenhum teste toca a rede.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

from app.core.config import Settings
from app.services.ingest import ytdlp as ytdlp_module
from app.services.ingest.errors import (
    VideoDownloadError,
    VideoTooLargeError,
    VideoUnavailableError,
)
from app.services.ingest.urls import validate_video_url
from app.services.ingest.ytdlp import (
    YtDlpDownloader,
    build_format_selector,
    build_ydl_options,
)

VALID_URL = "https://www.youtube.com/watch?v=abc123"


@pytest.fixture
def validated() -> Any:
    return validate_video_url(VALID_URL)


@pytest.fixture(autouse=True)
def _fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ytdlp_module, "require_ffmpeg", lambda: "/usr/bin/ffmpeg")


class FakeYoutubeDL:
    """Duplo de `yt_dlp.YoutubeDL` usado como context manager."""

    last_options: ClassVar[dict[str, Any]] = {}
    result: ClassVar[Any] = {}
    raises: ClassVar[Exception | None] = None

    def __init__(self, options: dict[str, Any]) -> None:
        FakeYoutubeDL.last_options = options

    def __enter__(self) -> FakeYoutubeDL:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> Any:
        if FakeYoutubeDL.raises is not None:
            raise FakeYoutubeDL.raises
        return FakeYoutubeDL.result


@pytest.fixture
def fake_ydl(monkeypatch: pytest.MonkeyPatch) -> type[FakeYoutubeDL]:
    FakeYoutubeDL.raises = None
    FakeYoutubeDL.result = {"id": "abc123", "ext": "mp4"}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


# --- opções ---------------------------------------------------------------


def test_options_pin_output_filename(settings: Settings, validated: Any, tmp_path: Path) -> None:
    options = build_ydl_options(settings, validated, tmp_path)

    assert options["outtmpl"]["default"] == "source.%(ext)s"
    assert options["paths"]["home"] == str(tmp_path)
    assert "%(title)s" not in options["outtmpl"]["default"]


def test_options_disable_playlists(settings: Settings, validated: Any, tmp_path: Path) -> None:
    options = build_ydl_options(settings, validated, tmp_path)

    assert options["noplaylist"] is True
    assert options["playlist_items"] == "1"


def test_options_disable_extra_downloads(
    settings: Settings, validated: Any, tmp_path: Path
) -> None:
    options = build_ydl_options(settings, validated, tmp_path)

    for key in (
        "writesubtitles",
        "writeautomaticsub",
        "writethumbnail",
        "writeinfojson",
        "getcomments",
    ):
        assert options[key] is False


def test_options_have_no_postprocessors(settings: Settings, validated: Any, tmp_path: Path) -> None:
    assert build_ydl_options(settings, validated, tmp_path)["postprocessors"] == []


def test_options_restrict_extractors(settings: Settings, validated: Any, tmp_path: Path) -> None:
    """Sem isso o extractor genérico do yt-dlp aceitaria qualquer host."""
    options = build_ydl_options(settings, validated, tmp_path)

    assert options["allowed_extractors"] == ["Youtube.*"]
    assert "generic" not in options["allowed_extractors"]


def test_options_carry_size_limit(settings: Settings, validated: Any, tmp_path: Path) -> None:
    options = build_ydl_options(settings, validated, tmp_path)

    assert options["max_filesize"] == settings.max_video_file_size_bytes


def test_format_selector_respects_max_height() -> None:
    selector = build_format_selector(720)

    assert "height<=720" in selector
    # Última alternativa sem restrição: não exigimos combinação impossível.
    assert selector.endswith("bestvideo+bestaudio/best")


def test_format_selector_prefers_mp4_first() -> None:
    assert build_format_selector(1080).startswith("bestvideo[height<=1080][ext=mp4]")


def test_skip_download_flag(settings: Settings, validated: Any, tmp_path: Path) -> None:
    assert build_ydl_options(settings, validated, tmp_path, download=False)["skip_download"] is True
    assert build_ydl_options(settings, validated, tmp_path, download=True)["skip_download"] is False


# --- tradução de erros ----------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "ERROR: Private video. Sign in if you've been granted access",
        "Video unavailable",
        "This video has been removed by the uploader",
        "The uploader has not made this video available in your country",
        "Sign in to confirm your age",
    ],
)
def test_unavailable_messages_map_to_video_unavailable(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any, message: str
) -> None:
    fake_ydl.raises = DownloadError(message)
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoUnavailableError):
        downloader.preflight()


def test_size_limit_message_maps_to_too_large(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.raises = DownloadError("File is larger than max-filesize (999 > 100)")
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoTooLargeError):
        downloader.download()


def test_generic_failure_maps_to_download_error(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.raises = ExtractorError("Unable to extract player response")
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoDownloadError):
        downloader.download()


def test_unsupported_error_maps_to_unavailable(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.raises = UnsupportedError(VALID_URL)
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoUnavailableError):
        downloader.preflight()


def test_ytdlp_message_never_reaches_the_error_shown_to_user(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.raises = DownloadError(
        "ERROR: unable to download https://cdn.interno/segredo?token=SECRETO"
    )
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoDownloadError) as exc:
        downloader.download()

    assert "SECRETO" not in exc.value.message
    assert "cdn.interno" not in exc.value.message


def test_os_error_maps_to_download_error(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.raises = OSError("disco cheio")
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoDownloadError, match="gravar"):
        downloader.download()


# --- forma do resultado ---------------------------------------------------


def test_none_result_is_an_error(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.result = None
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoDownloadError):
        downloader.download()


def test_playlist_result_returns_only_first_entry(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.result = {
        "_type": "playlist",
        "entries": [{"id": "primeiro"}, {"id": "segundo"}, {"id": "terceiro"}],
    }
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    info = downloader.download()

    assert info["id"] == "primeiro"


def test_empty_playlist_is_unavailable(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    fake_ydl.result = {"_type": "playlist", "entries": []}
    downloader = YtDlpDownloader(settings, validated, tmp_path)

    with pytest.raises(VideoUnavailableError):
        downloader.download()


def test_preflight_does_not_request_download(
    settings: Settings, validated: Any, tmp_path: Path, fake_ydl: Any
) -> None:
    YtDlpDownloader(settings, validated, tmp_path).preflight()

    assert fake_ydl.last_options["skip_download"] is True
