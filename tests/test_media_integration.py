"""Teste de integração: gera um vídeo curto com FFmpeg e faz o probe real.

Pulado automaticamente quando os binários não estão presentes, para que a
suíte continue verde em máquinas sem FFmpeg instalado.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.media.probe import probe_file, probe_storage_file

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/FFprobe não disponíveis neste ambiente",
)


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """Vídeo sintético de 1s, 320x240, 25fps, com faixa de áudio."""
    output = tmp_path / "sample.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None

    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=25:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return output


def test_probe_real_video(sample_video: Path) -> None:
    info = probe_file(sample_video, timeout=30)

    assert info.width == 320
    assert info.height == 240
    assert info.fps == 25.0
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert info.duration_seconds is not None and 0.8 <= info.duration_seconds <= 1.5
    assert info.container is not None and "mp4" in info.container
    assert info.has_video and info.has_audio
    assert info.is_vertical is False


def test_probe_real_video_through_storage(settings: Settings, sample_video: Path) -> None:
    settings.ensure_storage_dirs()
    target = settings.storage_path("downloads") / "sample.mp4"
    target.write_bytes(sample_video.read_bytes())

    info = probe_storage_file(settings, "downloads", "sample.mp4")

    assert info.video_codec == "h264"
    assert info.bitrate_bps is not None and info.bitrate_bps > 0


def test_probe_real_text_file_is_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "nao-video.mp4"
    fake.write_text("isto não é um vídeo")

    from app.services.media.errors import MediaProbeError

    with pytest.raises(MediaProbeError):
        probe_file(fake, timeout=30)
