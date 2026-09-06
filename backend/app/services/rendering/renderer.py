"""Renderização vertical dos clips.

Recebe arquivo de entrada, saída, dimensões e layout. Não conhece banco nem
jobs — quem orquestra é o handler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.schemas.media import MediaInfo
from app.schemas.settings import VideoSettings
from app.services.media.binaries import require_ffmpeg
from app.services.media.errors import MediaError
from app.services.media.probe import probe_file
from app.services.media.runner import run_command
from app.services.rendering.errors import RenderFailedError, RenderSourceUnavailableError
from app.services.rendering.filters import (
    AUDIO_ENCODING_ARGS,
    CONTAINER_ARGS,
    LayoutPlan,
    VerticalLayout,
    build_audio_filter,
    build_filtergraph,
    encoding_args_for,
    plan_layout,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RenderResult:
    path: Path
    filename: str
    size_bytes: int
    media_info: MediaInfo | None


def build_render_args(
    ffmpeg: str,
    source: Path,
    output: Path,
    *,
    plan: LayoutPlan,
    settings: VideoSettings | None = None,
    start_time: float | None = None,
    duration: float | None = None,
    subtitles: Path | None = None,
) -> list[str]:
    """Argumentos do render, opcionalmente recortando um intervalo da origem.

    Com `start_time`/`duration` o corte e a conversão vertical acontecem numa
    única passagem: não existe arquivo horizontal intermediário. `-ss` antes do
    `-i` é busca rápida e, como há re-encode, o FFmpeg decodifica até o instante
    exato.
    """
    resolved = settings or VideoSettings()

    trim: list[str] = []
    if start_time is not None:
        trim += ["-ss", f"{start_time:.3f}"]

    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        *trim,
        "-i",
        str(source),
    ]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]

    audio_filter = build_audio_filter(resolved.volume, resolved.normalize_audio)
    audio_filter_args = ["-af", audio_filter] if audio_filter else []

    return [
        *args,
        # filter_complex porque o layout com fundo desfocado precisa de duas
        # branches sobre a mesma origem; a saída rotulada `[v]` é mapeada
        # explicitamente, e `0:a?` mantém o áudio quando existir.
        "-filter_complex",
        build_filtergraph(
            plan,
            subtitles_path=str(subtitles) if subtitles is not None else None,
            blur_strength=resolved.blur_strength,
            background_darkness=resolved.background_darkness,
            fps=resolved.output_fps,
        ),
        "-map",
        "[v]",
        "-map",
        "0:a?",
        *audio_filter_args,
        *encoding_args_for(resolved.render_quality),
        *AUDIO_ENCODING_ARGS,
        *CONTAINER_ARGS,
        "-y",
        str(output),
    ]


class VerticalRenderer:
    """Converte um clip para o formato vertical de publicação."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ffmpeg = require_ffmpeg()

    def render(
        self,
        source: Path,
        output: Path,
        *,
        start_time: float | None = None,
        duration: float | None = None,
        subtitles: Path | None = None,
        source_size: tuple[int, int] | None = None,
        settings: VideoSettings | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> RenderResult:
        """Renderiza a origem (ou um intervalo dela) em 9:16.

        Passar `start_time`/`duration` recorta direto do vídeo original, e
        `subtitles` queima o `.ass` no mesmo filtergraph: corte, enquadramento,
        composição e legenda saem em um único encode.

        `source_size` evita um ffprobe por clip quando quem chama já conhece as
        dimensões do vídeo de origem.
        """
        if not source.is_file():
            raise RenderSourceUnavailableError("Clip de origem não encontrado.")

        target_width = width if width is not None else self._settings.output_width
        target_height = height if height is not None else self._settings.output_height

        resolved = settings or VideoSettings()
        plan = self._plan_for(source, source_size, resolved, target_width, target_height)

        output.parent.mkdir(parents=True, exist_ok=True)
        args = build_render_args(
            self._ffmpeg,
            source,
            output,
            plan=plan,
            settings=resolved,
            start_time=start_time,
            duration=duration,
            subtitles=subtitles,
        )

        try:
            result = run_command(args, timeout=self._settings.render_timeout_seconds)
        except Exception:
            self._discard(output)
            raise

        if result.returncode != 0:
            # stderr já foi logado pelo runner.
            self._discard(output)
            raise RenderFailedError("Falha ao renderizar o clip.")

        if not output.is_file() or output.stat().st_size == 0:
            self._discard(output)
            raise RenderFailedError("A renderização não produziu um arquivo utilizável.")

        media_info: MediaInfo | None
        try:
            media_info = probe_file(output, timeout=self._settings.ffprobe_timeout_seconds)
        except MediaError:
            logger.warning("Render gerado não pôde ser analisado", extra={"file": output.name})
            media_info = None

        return RenderResult(
            path=output,
            filename=output.name,
            size_bytes=output.stat().st_size,
            media_info=media_info,
        )

    def _plan_for(
        self,
        source: Path,
        source_size: tuple[int, int] | None,
        settings: VideoSettings,
        target_width: int,
        target_height: int,
    ) -> LayoutPlan:
        """Resolve a geometria; sem as dimensões da origem, cai no center_crop.

        Quem chama normalmente já tem largura e altura (vêm do ffprobe da
        ingestão), então o probe daqui é só a rede de segurança.
        """
        size = source_size or self._probe_size(source)
        if size is None:
            logger.warning(
                "Dimensões da origem desconhecidas; usando center_crop",
                extra={"file": source.name},
            )
            return plan_layout(
                target_width,
                target_height,
                VerticalLayout.CENTER_CROP,
                target_width=target_width,
                target_height=target_height,
            )

        return plan_layout(
            size[0],
            size[1],
            settings.layout,
            foreground_scale=settings.foreground_scale,
            target_width=target_width,
            target_height=target_height,
        )

    def _probe_size(self, source: Path) -> tuple[int, int] | None:
        try:
            info = probe_file(source, timeout=self._settings.ffprobe_timeout_seconds)
        except MediaError:
            return None
        if info is None or info.width is None or info.height is None:
            return None
        return info.width, info.height

    @staticmethod
    def _discard(output: Path) -> None:
        """Remove saída parcial: arquivo truncado é pior que arquivo ausente."""
        output.unlink(missing_ok=True)
