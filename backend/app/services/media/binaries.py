"""Descoberta de FFmpeg e FFprobe no ambiente.

O caminho do binário é resolvido uma vez via `shutil.which` e reutilizado nas
chamadas seguintes, para que o comando executado não dependa do PATH vigente no
momento da requisição.

O resultado é cacheado com TTL curto: `/health` pode ser chamado com frequência
alta por um load balancer e não deve disparar dois subprocessos por hit, mas
também não pode ficar preso a um resultado eterno se o operador instalar o
FFmpeg com o servidor no ar.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from app.services.media.errors import (
    FFmpegNotInstalledError,
    FFprobeNotInstalledError,
)
from app.services.media.runner import run_command

logger = logging.getLogger(__name__)

_VERSION_TIMEOUT_SECONDS = 10.0
_CACHE_TTL_SECONDS = 30.0
_VERSION_PATTERN = re.compile(r"^\w+ version (?P<version>\S+)")


class MediaBinary(StrEnum):
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"


@dataclass(frozen=True, slots=True)
class BinaryStatus:
    name: str
    available: bool
    version: str | None = None


_cache: dict[str, tuple[float, BinaryStatus]] = {}
_cache_lock = threading.Lock()


def _parse_version(output: str) -> str | None:
    """Extrai a versão da primeira linha de `ffmpeg -version`."""
    first_line = output.strip().splitlines()[0] if output.strip() else ""
    match = _VERSION_PATTERN.match(first_line)
    return match.group("version") if match else None


def _detect(binary: MediaBinary) -> BinaryStatus:
    executable = shutil.which(binary.value)
    if executable is None:
        return BinaryStatus(name=binary.value, available=False)

    try:
        result = run_command([executable, "-version"], timeout=_VERSION_TIMEOUT_SECONDS)
    except Exception:
        # Detecção nunca derruba o chamador: um binário quebrado é reportado
        # como indisponível, com o motivo no log.
        logger.exception("Falha ao consultar versão do binário", extra={"binary": binary.value})
        return BinaryStatus(name=binary.value, available=False)

    if result.returncode != 0:
        return BinaryStatus(name=binary.value, available=False)

    return BinaryStatus(name=binary.value, available=True, version=_parse_version(result.stdout))


def get_binary_status(binary: MediaBinary, *, use_cache: bool = True) -> BinaryStatus:
    now = time.monotonic()

    if use_cache:
        with _cache_lock:
            cached = _cache.get(binary.value)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    status = _detect(binary)
    with _cache_lock:
        _cache[binary.value] = (now, status)
    return status


def clear_binary_cache() -> None:
    """Descarta o cache de detecção. Usado em testes e após instalar binários."""
    with _cache_lock:
        _cache.clear()


def require_ffmpeg() -> str:
    """Caminho do executável do FFmpeg, ou erro se indisponível."""
    status = get_binary_status(MediaBinary.FFMPEG)
    if not status.available:
        raise FFmpegNotInstalledError
    path = shutil.which(MediaBinary.FFMPEG.value)
    if path is None:  # pragma: no cover - corrida entre detecção e uso
        clear_binary_cache()
        raise FFmpegNotInstalledError
    return path


def require_ffprobe() -> str:
    """Caminho do executável do FFprobe, ou erro se indisponível."""
    status = get_binary_status(MediaBinary.FFPROBE)
    if not status.available:
        raise FFprobeNotInstalledError
    path = shutil.which(MediaBinary.FFPROBE.value)
    if path is None:  # pragma: no cover - corrida entre detecção e uso
        clear_binary_cache()
        raise FFprobeNotInstalledError
    return path
