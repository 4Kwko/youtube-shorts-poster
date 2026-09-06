from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.services.media import binaries as binaries_module
from app.services.media import probe as probe_module
from app.services.media.binaries import (
    MediaBinary,
    clear_binary_cache,
    get_binary_status,
    require_ffmpeg,
    require_ffprobe,
)
from app.services.media.errors import (
    FFmpegNotInstalledError,
    FFprobeNotInstalledError,
    InvalidMediaFileError,
    MediaProbeError,
    MediaProcessingError,
)
from app.services.media.runner import CommandResult, run_command

FFPROBE_VERSION_OUTPUT = "ffprobe version 6.1.1-3ubuntu5 Copyright (c) 2007-2023\nbuilt with gcc\n"


@pytest.fixture(autouse=True)
def _reset_binary_cache() -> None:
    clear_binary_cache()


# --- detecção de binários -------------------------------------------------


def test_ffmpeg_unavailable_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)

    status = get_binary_status(MediaBinary.FFMPEG)

    assert status.available is False
    assert status.version is None


def test_require_ffmpeg_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)

    with pytest.raises(FFmpegNotInstalledError) as exc:
        require_ffmpeg()

    assert exc.value.status_code == 503
    assert exc.value.code == "ffmpeg_unavailable"


def test_require_ffprobe_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)

    with pytest.raises(FFprobeNotInstalledError) as exc:
        require_ffprobe()

    assert exc.value.code == "ffprobe_unavailable"


def test_version_is_parsed_from_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        binaries_module,
        "run_command",
        lambda args, timeout: CommandResult(0, FFPROBE_VERSION_OUTPUT, ""),
    )

    status = get_binary_status(MediaBinary.FFPROBE)

    assert status.available is True
    assert status.version == "6.1.1-3ubuntu5"


def test_binary_with_nonzero_exit_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        binaries_module,
        "run_command",
        lambda args, timeout: CommandResult(1, "", "erro"),
    )

    assert get_binary_status(MediaBinary.FFMPEG).available is False


def test_broken_binary_does_not_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(args: list[str], timeout: float) -> CommandResult:
        raise MediaProcessingError("falhou")

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(binaries_module, "run_command", _boom)

    assert get_binary_status(MediaBinary.FFMPEG).available is False


def test_detection_result_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _counting(name: str) -> str | None:
        calls.append(name)
        return None

    monkeypatch.setattr(shutil, "which", _counting)

    get_binary_status(MediaBinary.FFMPEG)
    get_binary_status(MediaBinary.FFMPEG)

    assert len(calls) == 1

    get_binary_status(MediaBinary.FFMPEG, use_cache=False)
    assert len(calls) == 2


# --- runner ---------------------------------------------------------------


def test_run_command_never_uses_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    run_command(["/usr/bin/ffprobe", "-version"], timeout=5)

    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["timeout"] == 5
    assert isinstance(captured["args"], list)


def test_run_command_returns_nonzero_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 3, "", "detalhe interno"),
    )

    result = run_command(["/usr/bin/ffprobe"], timeout=5)

    assert result.returncode == 3


def test_run_command_wraps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _timeout(args: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout)

    with pytest.raises(MediaProcessingError, match="tempo limite"):
        run_command(["/usr/bin/ffprobe"], timeout=1)


def test_run_command_wraps_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(args: list[str], **kwargs: Any) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", _missing)

    with pytest.raises(MediaProcessingError):
        run_command(["/usr/bin/ffprobe"], timeout=1)


def test_run_command_rejects_empty_args() -> None:
    with pytest.raises(ValueError, match="vazia"):
        run_command([], timeout=1)


# --- probe: arquivos inválidos e falhas de processo -----------------------


def test_probe_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidMediaFileError, match="não encontrado"):
        probe_module.probe_file(tmp_path / "ausente.mp4", timeout=5)


def test_probe_directory(tmp_path: Path) -> None:
    with pytest.raises(InvalidMediaFileError, match="não é um arquivo"):
        probe_module.probe_file(tmp_path, timeout=5)


def test_probe_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "vazio.mp4"
    empty.touch()

    with pytest.raises(InvalidMediaFileError, match="vazio"):
        probe_module.probe_file(empty, timeout=5)


def test_probe_nonzero_exit_does_not_leak_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "quebrado.mp4"
    media.write_bytes(b"nao e video")

    monkeypatch.setattr(probe_module, "require_ffprobe", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        probe_module,
        "run_command",
        lambda args, timeout: CommandResult(1, "", "/srv/interno/quebrado.mp4: Invalid data"),
    )

    with pytest.raises(MediaProbeError) as exc:
        probe_module.probe_file(media, timeout=5)

    assert "/srv/" not in exc.value.message
    assert "Invalid data" not in exc.value.message


def test_probe_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"dados")

    monkeypatch.setattr(probe_module, "require_ffprobe", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        probe_module, "run_command", lambda args, timeout: CommandResult(0, "nao-json", "")
    )

    with pytest.raises(MediaProbeError, match="Resposta inesperada"):
        probe_module.probe_file(media, timeout=5)


def test_probe_requires_ffprobe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"dados")
    monkeypatch.setattr(shutil, "which", lambda _: None)

    with pytest.raises(FFprobeNotInstalledError):
        probe_module.probe_file(media, timeout=5)


def test_ffprobe_args_are_a_list_with_terminator() -> None:
    args = probe_module._build_ffprobe_args("/usr/bin/ffprobe", Path("/storage/downloads/-x.mp4"))

    assert isinstance(args, list)
    assert args[0] == "/usr/bin/ffprobe"
    assert args[-2] == "-i"
    assert args[-1] == str(Path("/storage/downloads/-x.mp4"))


# --- probe via storage ----------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["../../etc/passwd", "sub/dir.mp4", "..", "", "  ", "nome\x00.mp4", "a\\b.mp4"],
    ids=["traversal", "subdir", "dotdot", "empty", "blank", "nul", "backslash"],
)
def test_storage_probe_rejects_unsafe_names(settings: Settings, filename: str) -> None:
    settings.ensure_storage_dirs()

    with pytest.raises(InvalidMediaFileError, match="Referência de arquivo inválida"):
        probe_module.probe_storage_file(settings, "downloads", filename)


def test_storage_probe_rejects_unknown_subdir(settings: Settings) -> None:
    settings.ensure_storage_dirs()

    with pytest.raises(InvalidMediaFileError):
        probe_module.probe_storage_file(settings, "../secrets", "video.mp4")


def test_storage_probe_resolves_inside_storage(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.ensure_storage_dirs()
    media = settings.storage_path("downloads") / "video.mp4"
    media.write_bytes(b"dados")

    seen: dict[str, Path] = {}

    def _fake_probe(path: Path, *, timeout: float) -> object:
        seen["path"] = path
        raise MediaProbeError("parado aqui")

    monkeypatch.setattr(probe_module, "probe_file", _fake_probe)

    with pytest.raises(MediaProbeError):
        probe_module.probe_storage_file(settings, "downloads", "video.mp4")

    assert seen["path"] == media.resolve()
