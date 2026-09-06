"""Testes do orquestrador de ingestão.

Nenhum acesso a rede: o downloader é substituído por um duplo que escreve
arquivos no workspace, exatamente como o yt-dlp faria.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.services.ingest.errors import (
    InvalidVideoURLError,
    LiveStreamNotSupportedError,
    UnsupportedVideoURLError,
    VideoDownloadError,
    VideoTooLargeError,
    VideoTooLongError,
    VideoUnavailableError,
)
from app.services.ingest.service import DOWNLOADS_SUBDIR, import_video, workspace_for
from app.services.ingest.urls import ValidatedVideoURL

VALID_URL = "https://www.youtube.com/watch?v=abc123"

BASE_INFO: dict[str, Any] = {
    "id": "abc123",
    "title": "Vídeo de exemplo",
    "duration": 120.0,
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "vcodec": "avc1.640028",
    "acodec": "mp4a.40.2",
    "ext": "mp4",
}


class FakeDownloader:
    """Duplo do yt-dlp: grava bytes no workspace e devolve metadata."""

    def __init__(
        self,
        workspace: Path,
        *,
        info: dict[str, Any] | None = None,
        preflight_info: dict[str, Any] | None = None,
        file_bytes: bytes = b"video-bytes",
        filename: str = "source.mp4",
        write_file: bool = True,
        preflight_error: Exception | None = None,
        download_error: Exception | None = None,
        report_path: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.info = info if info is not None else dict(BASE_INFO)
        self.preflight_info = preflight_info if preflight_info is not None else dict(BASE_INFO)
        self.file_bytes = file_bytes
        self.filename = filename
        self.write_file = write_file
        self.preflight_error = preflight_error
        self.download_error = download_error
        self.report_path = report_path
        self.download_called = False

    def preflight(self) -> dict[str, Any]:
        if self.preflight_error is not None:
            raise self.preflight_error
        return self.preflight_info

    def download(self) -> dict[str, Any]:
        self.download_called = True
        if self.download_error is not None:
            raise self.download_error
        if self.write_file:
            (self.workspace / self.filename).write_bytes(self.file_bytes)
        result = dict(self.info)
        if self.report_path is not None:
            result["requested_downloads"] = [{"filepath": self.report_path}]
        return result


def make_factory(**kwargs: Any) -> Any:
    """Factory que registra o duplo criado, para inspeção no teste."""
    created: list[FakeDownloader] = []

    def factory(
        settings: Settings, validated: ValidatedVideoURL, workspace: Path
    ) -> FakeDownloader:
        downloader = FakeDownloader(workspace, **kwargs)
        created.append(downloader)
        return downloader

    factory.created = created  # type: ignore[attr-defined]
    return factory


@pytest.fixture
def ingest_settings(settings: Settings) -> Settings:
    settings.ensure_storage_dirs()
    return settings


def _downloads_root(settings: Settings) -> Path:
    return settings.storage_path(DOWNLOADS_SUBDIR)


# --- caminho feliz --------------------------------------------------------


def test_successful_import(ingest_settings: Settings) -> None:
    info = import_video(ingest_settings, VALID_URL, downloader_factory=make_factory())

    assert info.provider == "youtube"
    assert info.provider_video_id == "abc123"
    assert info.title == "Vídeo de exemplo"
    assert info.local_filename == "source.mp4"
    assert info.file_size_bytes == len(b"video-bytes")
    assert len(info.id) == 32

    stored = _downloads_root(ingest_settings) / info.id / info.local_filename
    assert stored.is_file()


def test_video_id_is_unpredictable_and_unique(ingest_settings: Settings) -> None:
    ids = {
        import_video(ingest_settings, VALID_URL, downloader_factory=make_factory()).id
        for _ in range(5)
    }

    assert len(ids) == 5
    assert all(id_.isalnum() for id_ in ids)


def test_workspace_is_isolated_per_video(ingest_settings: Settings) -> None:
    first = import_video(ingest_settings, VALID_URL, downloader_factory=make_factory())
    second = import_video(ingest_settings, VALID_URL, downloader_factory=make_factory())

    assert workspace_for(ingest_settings, first.id) != workspace_for(ingest_settings, second.id)
    assert workspace_for(ingest_settings, first.id).is_dir()


def test_playlist_url_imports_single_video(ingest_settings: Settings) -> None:
    factory = make_factory()

    info = import_video(
        ingest_settings,
        "https://www.youtube.com/watch?v=abc123&list=PL0000&index=7",
        downloader_factory=factory,
    )

    assert "list=" not in info.source_url
    assert len(list(_downloads_root(ingest_settings).iterdir())) == 1


# --- URLs rejeitadas ------------------------------------------------------


def test_invalid_url_does_not_touch_storage(ingest_settings: Settings) -> None:
    with pytest.raises(InvalidVideoURLError):
        import_video(ingest_settings, "file:///etc/passwd", downloader_factory=make_factory())

    assert list(_downloads_root(ingest_settings).iterdir()) == []


def test_unsupported_url_does_not_touch_storage(ingest_settings: Settings) -> None:
    with pytest.raises(UnsupportedVideoURLError):
        import_video(ingest_settings, "https://evil.com/v.mp4", downloader_factory=make_factory())

    assert list(_downloads_root(ingest_settings).iterdir()) == []


def test_invalid_url_never_calls_downloader(ingest_settings: Settings) -> None:
    factory = make_factory()

    with pytest.raises(InvalidVideoURLError):
        import_video(ingest_settings, "ftp://youtube.com/x", downloader_factory=factory)

    assert factory.created == []


# --- limites --------------------------------------------------------------


def test_rejects_video_longer_than_limit(ingest_settings: Settings) -> None:
    long_info = {**BASE_INFO, "duration": ingest_settings.max_video_duration_seconds + 1}
    factory = make_factory(preflight_info=long_info)

    with pytest.raises(VideoTooLongError):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert factory.created[0].download_called is False
    assert list(_downloads_root(ingest_settings).iterdir()) == []


def test_rejects_estimated_size_above_limit(ingest_settings: Settings) -> None:
    big = {**BASE_INFO, "filesize_approx": ingest_settings.max_video_file_size_bytes + 1}
    factory = make_factory(preflight_info=big)

    with pytest.raises(VideoTooLargeError):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert factory.created[0].download_called is False


def test_rejects_real_size_above_limit_after_download(settings: Settings) -> None:
    """A metadata prévia mentiu: o limite real é conferido no disco."""
    settings = settings.model_copy(update={"max_video_file_size_bytes": 10})
    settings.ensure_storage_dirs()
    factory = make_factory(preflight_info={**BASE_INFO, "filesize": 5}, file_bytes=b"x" * 100)

    with pytest.raises(VideoTooLargeError):
        import_video(settings, VALID_URL, downloader_factory=factory)

    assert factory.created[0].download_called is True
    assert list(_downloads_root(settings).iterdir()) == []


def test_rejects_live_stream(ingest_settings: Settings) -> None:
    factory = make_factory(preflight_info={**BASE_INFO, "is_live": True})

    with pytest.raises(LiveStreamNotSupportedError):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert factory.created[0].download_called is False


# --- falhas do downloader -------------------------------------------------


def test_video_unavailable_is_propagated(ingest_settings: Settings) -> None:
    factory = make_factory(preflight_error=VideoUnavailableError("indisponível"))

    with pytest.raises(VideoUnavailableError):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert list(_downloads_root(ingest_settings).iterdir()) == []


def test_download_error_cleans_up_partial_files(ingest_settings: Settings) -> None:
    factory = make_factory(download_error=VideoDownloadError("falhou no meio"))

    with pytest.raises(VideoDownloadError):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert list(_downloads_root(ingest_settings).iterdir()) == []


def test_unexpected_exception_also_cleans_up(ingest_settings: Settings) -> None:
    factory = make_factory(download_error=RuntimeError("bug inesperado"))

    with pytest.raises(RuntimeError):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert list(_downloads_root(ingest_settings).iterdir()) == []


def test_success_reported_but_no_file_produced(ingest_settings: Settings) -> None:
    factory = make_factory(write_file=False)

    with pytest.raises(VideoDownloadError, match="não produziu um arquivo"):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert list(_downloads_root(ingest_settings).iterdir()) == []


def test_empty_file_is_rejected(ingest_settings: Settings) -> None:
    factory = make_factory(file_bytes=b"")

    with pytest.raises(VideoDownloadError, match="vazio"):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert list(_downloads_root(ingest_settings).iterdir()) == []


# --- caminhos hostis ------------------------------------------------------


def test_reported_path_outside_workspace_is_ignored(
    ingest_settings: Settings, tmp_path: Path
) -> None:
    """yt-dlp anunciando caminho fora do workspace não é seguido."""
    outsider = tmp_path / "fora.mp4"
    outsider.write_bytes(b"conteudo externo")

    factory = make_factory(report_path=str(outsider))
    info = import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    # Caiu no arquivo real do workspace, não no caminho anunciado.
    assert info.local_filename == "source.mp4"
    assert outsider.read_bytes() == b"conteudo externo"


def test_traversal_path_report_is_ignored(ingest_settings: Settings) -> None:
    factory = make_factory(report_path="../../../etc/passwd")

    info = import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert info.local_filename == "source.mp4"


def test_traversal_path_with_no_local_file_fails_closed(ingest_settings: Settings) -> None:
    factory = make_factory(report_path="../../../etc/passwd", write_file=False)

    with pytest.raises(VideoDownloadError):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)


def test_temp_artifacts_are_not_mistaken_for_the_result(ingest_settings: Settings) -> None:
    factory = make_factory(filename="source.mp4.part")

    with pytest.raises(VideoDownloadError, match="não produziu um arquivo"):
        import_video(ingest_settings, VALID_URL, downloader_factory=factory)


def test_largest_file_wins_when_fragments_remain(ingest_settings: Settings) -> None:
    class FragmentDownloader(FakeDownloader):
        def download(self) -> dict[str, Any]:
            (self.workspace / "source.f137.mp4").write_bytes(b"x" * 10)
            (self.workspace / "source.mp4").write_bytes(b"x" * 500)
            return dict(self.info)

    def factory(settings: Settings, validated: ValidatedVideoURL, workspace: Path) -> Any:
        return FragmentDownloader(workspace)

    info = import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert info.local_filename == "source.mp4"
    assert info.file_size_bytes == 500


# --- metadata incompleta --------------------------------------------------


def test_import_succeeds_with_minimal_metadata(ingest_settings: Settings) -> None:
    factory = make_factory(info={}, preflight_info={})

    info = import_video(ingest_settings, VALID_URL, downloader_factory=factory)

    assert info.title is None
    assert info.duration_seconds is None
    assert info.provider_video_id is None
    assert info.local_filename == "source.mp4"
    assert info.file_size_bytes is not None and info.file_size_bytes > 0
