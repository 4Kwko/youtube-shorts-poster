from __future__ import annotations

import pytest

from app.services.ingest.errors import InvalidVideoURLError, UnsupportedVideoURLError
from app.services.ingest.urls import strip_playlist_params, validate_video_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "http://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://m.youtube.com/watch?v=abc123",
        "https://youtube.com/shorts/abc123",
        "https://vimeo.com/123456789",
        "  https://www.youtube.com/watch?v=abc123  ",
    ],
)
def test_accepts_supported_urls(url: str) -> None:
    validated = validate_video_url(url)

    assert validated.provider.name in {"youtube", "vimeo"}
    assert validated.url.startswith(("http://", "https://"))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/video.mp4",
        "data:text/html,<script>",
        "javascript:alert(1)",
        "/home/user/video.mp4",
        "C:\\videos\\file.mp4",
        "../../etc/passwd",
        "não é uma url",
        "",
        "   ",
        "https://",
        "http://",
    ],
)
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(InvalidVideoURLError):
        validate_video_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/watch?v=x",
        "http://localhost/watch?v=x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/video",
        "http://10.0.0.5/video.mp4",
        "http://192.168.1.1/video",
    ],
    ids=["loopback", "localhost", "metadata", "ipv6", "private-a", "private-c"],
)
def test_rejects_ssrf_targets(url: str) -> None:
    """Hosts internos nunca chegam ao yt-dlp: ou são IP literal, ou não estão na allowlist."""
    with pytest.raises((InvalidVideoURLError, UnsupportedVideoURLError)):
        validate_video_url(url)


def test_rejects_credentials_in_url() -> None:
    with pytest.raises(InvalidVideoURLError, match="credenciais"):
        validate_video_url("https://user:senha@www.youtube.com/watch?v=abc")


@pytest.mark.parametrize("port", [22, 8080, 3000])
def test_rejects_unusual_ports(port: int) -> None:
    with pytest.raises(InvalidVideoURLError, match="Porta"):
        validate_video_url(f"https://www.youtube.com:{port}/watch?v=abc")


def test_rejects_control_characters() -> None:
    with pytest.raises(InvalidVideoURLError, match="controle"):
        validate_video_url("https://www.youtube.com/watch?v=abc\n\rHost: evil")


def test_rejects_oversized_url() -> None:
    with pytest.raises(InvalidVideoURLError, match="tamanho máximo"):
        validate_video_url("https://www.youtube.com/watch?v=" + "a" * 3000)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video.mp4",
        "https://evil.com/watch?v=abc",
        "https://notyoutube.com/watch?v=abc",
        "https://youtube.com.evil.com/watch?v=abc",
    ],
)
def test_rejects_unsupported_hosts(url: str) -> None:
    with pytest.raises(UnsupportedVideoURLError):
        validate_video_url(url)


# --- playlists ------------------------------------------------------------


def test_strips_playlist_params() -> None:
    validated = validate_video_url("https://www.youtube.com/watch?v=abc123&list=PL9999&index=4")

    assert "list=" not in validated.url
    assert "index=" not in validated.url
    assert "v=abc123" in validated.url
    assert validated.had_playlist_params is True


def test_url_without_playlist_params_is_unchanged() -> None:
    original = "https://www.youtube.com/watch?v=abc123"

    validated = validate_video_url(original)

    assert validated.url == original
    assert validated.had_playlist_params is False


def test_pure_playlist_url_keeps_no_playlist_param() -> None:
    """URL só de playlist perde o parâmetro; o downloader ainda recusa por noplaylist."""
    cleaned, changed = strip_playlist_params("https://www.youtube.com/playlist?list=PL9999")

    assert changed is True
    assert "list=" not in cleaned


def test_host_is_lowercased() -> None:
    validated = validate_video_url("https://WWW.YouTube.COM/watch?v=abc")

    assert validated.host == "www.youtube.com"
    assert validated.provider.name == "youtube"
