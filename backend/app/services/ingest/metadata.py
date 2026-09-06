"""Normalização da metadata bruta do yt-dlp para os schemas internos.

Tudo aqui é função pura sobre dicionários: não toca disco, rede nem yt-dlp.
É o ponto onde a metadata externa deixa de ser confiável e vira dado tipado.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from app.schemas.ingest import VideoSourceInfo
from app.schemas.media import MediaInfo

MAX_TITLE_LENGTH = 300

# yt-dlp usa a string "none" quando a faixa não existe no formato escolhido.
_ABSENT_CODEC = frozenset({"none", "", "unknown"})


@dataclass(frozen=True, slots=True)
class PreflightInfo:
    """Metadata conhecida antes do download, usada para recusar cedo."""

    provider_video_id: str | None
    title: str | None
    duration_seconds: float | None
    height: int | None
    estimated_size_bytes: int | None
    is_live: bool


def sanitize_title(value: Any) -> str | None:
    """Título seguro para log e exibição.

    Nunca influencia caminho de arquivo — o nome no disco é fixo. Aqui só
    removemos caracteres de controle e limitamos o tamanho para não poluir log
    nem quebrar terminal.
    """
    if not isinstance(value, str):
        return None

    normalized = unicodedata.normalize("NFC", value)
    cleaned = "".join(char for char in normalized if unicodedata.category(char)[0] != "C").strip()

    if not cleaned:
        return None
    return cleaned[:MAX_TITLE_LENGTH]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else None


def _as_codec(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    codec = value.strip().lower()
    if codec in _ABSENT_CODEC:
        return None
    # yt-dlp reporta perfis completos como "avc1.640028"; guardamos a família.
    return codec.split(".")[0]


def _as_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def extract_preflight(info: Any) -> PreflightInfo:
    """Lê da metadata prévia apenas o necessário para decidir se vale baixar."""
    data: dict[str, Any] = info if isinstance(info, dict) else {}

    size = _as_int(data.get("filesize")) or _as_int(data.get("filesize_approx"))

    return PreflightInfo(
        provider_video_id=_as_str(data.get("id")),
        title=sanitize_title(data.get("title")),
        duration_seconds=_as_float(data.get("duration")),
        height=_as_int(data.get("height")),
        estimated_size_bytes=size,
        is_live=bool(data.get("is_live") or data.get("live_status") == "is_live"),
    )


def build_source_info(
    *,
    video_id: str,
    source_url: str,
    provider: str,
    local_filename: str,
    file_size_bytes: int,
    info: Any,
    media_info: MediaInfo | None,
) -> VideoSourceInfo:
    """Combina metadata do yt-dlp com a do ffprobe.

    O ffprobe descreve o arquivo que realmente está em disco depois de merge e
    remux, então ele tem precedência sobre o que o provedor anunciou.
    """
    data: dict[str, Any] = info if isinstance(info, dict) else {}

    return VideoSourceInfo(
        id=video_id,
        source_url=source_url,
        provider=provider,
        provider_video_id=_as_str(data.get("id")),
        title=sanitize_title(data.get("title")),
        duration_seconds=(
            media_info.duration_seconds
            if media_info and media_info.duration_seconds is not None
            else _as_float(data.get("duration"))
        ),
        width=(
            media_info.width
            if media_info and media_info.width is not None
            else _as_int(data.get("width"))
        ),
        height=(
            media_info.height
            if media_info and media_info.height is not None
            else _as_int(data.get("height"))
        ),
        fps=(
            media_info.fps
            if media_info and media_info.fps is not None
            else _as_float(data.get("fps"))
        ),
        video_codec=(
            media_info.video_codec
            if media_info and media_info.video_codec is not None
            else _as_codec(data.get("vcodec"))
        ),
        audio_codec=(
            media_info.audio_codec
            if media_info and media_info.audio_codec is not None
            else _as_codec(data.get("acodec"))
        ),
        container=(
            media_info.container
            if media_info and media_info.container is not None
            else _as_str(data.get("ext"))
        ),
        file_size_bytes=file_size_bytes,
        local_filename=local_filename,
    )
