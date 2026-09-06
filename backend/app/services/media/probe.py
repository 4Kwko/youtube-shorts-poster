"""Extração de metadata via ffprobe.

`parse_probe_payload` é uma função pura sobre o JSON do ffprobe, o que permite
testar todo o parsing sem tocar em disco nem em subprocesso. A parte que fala
com o mundo (`probe_file`) só monta os argumentos e delega.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.media import MediaInfo
from app.services.media.binaries import require_ffprobe
from app.services.media.errors import InvalidMediaFileError, MediaProbeError
from app.services.media.runner import run_command
from app.utils.paths import resolve_storage_file

logger = logging.getLogger(__name__)


def _build_ffprobe_args(executable: str, path: Path) -> list[str]:
    return [
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        # Encerra o parsing de opções: um arquivo cujo nome comece com "-"
        # não pode ser interpretado como flag.
        "-i",
        str(path),
    ]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else None


def _parse_frame_rate(value: Any) -> float | None:
    """Converte a fração do ffprobe ("30000/1001") em FPS decimal."""
    if not isinstance(value, str) or "/" not in value:
        return _as_float(value)

    numerator, _, denominator = value.partition("/")
    try:
        num, den = float(numerator), float(denominator)
    except ValueError:
        return None
    if den == 0 or num <= 0:
        return None
    return round(num / den, 3)


def _first_stream(streams: list[dict[str, Any]], codec_type: str) -> dict[str, Any] | None:
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == codec_type:
            return stream
    return None


def parse_probe_payload(payload: Any) -> MediaInfo:
    """Converte o JSON do ffprobe em `MediaInfo`.

    Levanta `MediaProbeError` se o payload não tiver a forma esperada ou não
    contiver nenhuma stream reconhecível.
    """
    if not isinstance(payload, dict):
        raise MediaProbeError("Não foi possível interpretar a metadata do arquivo.")

    raw_streams = payload.get("streams")
    streams: list[dict[str, Any]] = (
        [s for s in raw_streams if isinstance(s, dict)] if isinstance(raw_streams, list) else []
    )

    raw_format = payload.get("format")
    fmt: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}

    video = _first_stream(streams, "video")
    audio = _first_stream(streams, "audio")

    if video is None and audio is None:
        raise MediaProbeError("O arquivo não contém faixas de áudio ou vídeo reconhecíveis.")

    duration = _as_float(fmt.get("duration"))
    if duration is None and video is not None:
        duration = _as_float(video.get("duration"))
    if duration is None and audio is not None:
        duration = _as_float(audio.get("duration"))

    fps: float | None = None
    if video is not None:
        # avg_frame_rate reflete melhor VFR; r_frame_rate é o fallback.
        fps = _parse_frame_rate(video.get("avg_frame_rate")) or _parse_frame_rate(
            video.get("r_frame_rate")
        )

    return MediaInfo(
        duration_seconds=duration,
        width=_as_int(video.get("width")) if video else None,
        height=_as_int(video.get("height")) if video else None,
        fps=fps,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        bitrate_bps=_as_int(fmt.get("bit_rate")),
        container=fmt.get("format_name") if isinstance(fmt.get("format_name"), str) else None,
    )


def _validate_media_path(path: Path) -> None:
    if not path.exists():
        raise InvalidMediaFileError("Arquivo de mídia não encontrado.")
    if not path.is_file():
        raise InvalidMediaFileError("O caminho informado não é um arquivo.")
    if path.stat().st_size == 0:
        raise InvalidMediaFileError("Arquivo de mídia vazio.")


def probe_file(path: Path, *, timeout: float) -> MediaInfo:
    """Extrai metadata de um caminho já validado como interno ao servidor.

    Não use diretamente com entrada da API — passe por `probe_storage_file`.
    """
    _validate_media_path(path)
    executable = require_ffprobe()

    result = run_command(_build_ffprobe_args(executable, path), timeout=timeout)

    if result.returncode != 0:
        # O stderr já foi logado pelo runner; o cliente recebe só o motivo.
        raise MediaProbeError("Não foi possível analisar o arquivo de mídia.")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.error("ffprobe devolveu JSON inválido", extra={"stdout_head": result.stdout[:500]})
        raise MediaProbeError("Resposta inesperada ao analisar o arquivo de mídia.") from exc

    return parse_probe_payload(payload)


def probe_storage_file(settings: Settings, subdir: str, filename: str) -> MediaInfo:
    """Ponto de entrada para nomes vindos de fora do servidor.

    O caminho é sempre derivado do storage; nada do que o cliente enviar chega
    ao ffprobe como caminho.
    """
    try:
        path = resolve_storage_file(settings, subdir, filename)
    except ValueError as exc:
        logger.warning("Referência de arquivo rejeitada", extra={"subdir": subdir})
        raise InvalidMediaFileError("Referência de arquivo inválida.") from exc

    return probe_file(path, timeout=settings.ffprobe_timeout_seconds)
