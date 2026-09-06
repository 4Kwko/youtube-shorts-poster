"""Geração dos clips com FFmpeg.

Usa a camada de mídia existente (`services.media`): lista de argumentos,
timeout e tratamento de stderr já estão resolvidos lá. Este módulo só decide
*o que* pedir ao FFmpeg.

Nesta etapa o clip mantém a proporção original — nada de 9:16 ainda.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.schemas.media import MediaInfo
from app.services.clipping.errors import ClipGenerationError, ClipSourceUnavailableError
from app.services.clipping.intervals import ClipInterval
from app.services.media.binaries import require_ffmpeg
from app.services.media.errors import MediaError
from app.services.media.probe import probe_file
from app.services.media.runner import run_command

logger = logging.getLogger(__name__)

CLIP_EXTENSION = "mp4"
# Zero-padding em 3 dígitos: ordena corretamente no shell e no listing.
CLIP_NAME_TEMPLATE = "{sequence:03d}." + CLIP_EXTENSION


@dataclass(frozen=True, slots=True)
class ClipArtifact:
    interval: ClipInterval
    path: Path
    filename: str
    size_bytes: int
    media_info: MediaInfo | None


def clip_filename(sequence: int) -> str:
    return CLIP_NAME_TEMPLATE.format(sequence=sequence)


def build_clip_args(ffmpeg: str, source: Path, interval: ClipInterval, output: Path) -> list[str]:
    """Argumentos do corte.

    Re-encode em vez de stream copy: com `-c copy` o corte salta para o
    keyframe mais próximo, e um clip de 90s pode começar segundos fora do
    ponto pedido. Precisão temporal importa mais aqui do que tempo de CPU.
    """
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        # `-ss` antes do input é busca rápida; com re-encode o FFmpeg ainda
        # decodifica até o instante exato.
        "-ss",
        f"{interval.start_time:.3f}",
        "-i",
        str(source),
        "-t",
        f"{interval.duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-avoid_negative_ts",
        "make_zero",
        "-y",
        str(output),
    ]


class FixedClipper:
    """Corta um vídeo em trechos sequenciais de duração fixa."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ffmpeg = require_ffmpeg()

    def _render_one(self, source: Path, interval: ClipInterval, output_dir: Path) -> ClipArtifact:
        output = output_dir / clip_filename(interval.sequence)
        args = build_clip_args(self._ffmpeg, source, interval, output)

        result = run_command(args, timeout=self._settings.clip_timeout_seconds)
        if result.returncode != 0:
            # O stderr já foi logado pelo runner.
            raise ClipGenerationError("Falha ao gerar um dos clips.")

        if not output.is_file() or output.stat().st_size == 0:
            raise ClipGenerationError("O corte não produziu um arquivo utilizável.")

        media_info: MediaInfo | None
        try:
            media_info = probe_file(output, timeout=self._settings.ffprobe_timeout_seconds)
        except MediaError:
            logger.warning(
                "Clip gerado não pôde ser analisado", extra={"sequence": interval.sequence}
            )
            media_info = None

        return ClipArtifact(
            interval=interval,
            path=output,
            filename=output.name,
            size_bytes=output.stat().st_size,
            media_info=media_info,
        )

    def create_clips(
        self,
        source: Path,
        intervals: list[ClipInterval],
        output_dir: Path,
        *,
        on_clip_done: Callable[[int, int], None] | None = None,
    ) -> list[ClipArtifact]:
        """Gera todos os clips ou nenhum.

        Falha no meio remove o diretório inteiro: um conjunto parcial de
        arquivos sem registros correspondentes é pior do que nenhum.
        """
        if not source.is_file():
            raise ClipSourceUnavailableError("Arquivo de origem não encontrado.")

        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[ClipArtifact] = []

        try:
            for interval in intervals:
                artifacts.append(self._render_one(source, interval, output_dir))
                if on_clip_done is not None:
                    on_clip_done(len(artifacts), len(intervals))
        except Exception:
            self.cleanup(output_dir)
            raise

        return artifacts

    @staticmethod
    def cleanup(output_dir: Path) -> None:
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
