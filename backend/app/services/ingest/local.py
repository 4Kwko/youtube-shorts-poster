"""Importação de um arquivo de vídeo escolhido pelo usuário.

Exceção deliberada ao storage interno, como a exportação: este módulo lê de um
caminho externo. O arquivo original é apenas lido — nunca movido, alterado ou
apagado. O pipeline trabalha sobre a cópia interna.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import Settings
from app.schemas.ingest import VideoSourceInfo
from app.services.ingest.errors import (
    InvalidVideoURLError,
    VideoDownloadError,
    VideoTooLargeError,
    VideoTooLongError,
)
from app.services.ingest.metadata import build_source_info, sanitize_title
from app.services.ingest.progress import (
    STAGE_PROGRESS,
    IngestStage,
    ProgressCallback,
    noop_progress,
)
from app.services.media.errors import MediaError
from app.services.media.probe import probe_file
from app.utils.paths import validate_filename

logger = logging.getLogger(__name__)

LOCAL_PROVIDER = "local"

# Extensões oferecidas no diálogo. Não são garantia de nada: quem decide se o
# arquivo é utilizável é o ffprobe.
ALLOWED_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"})

COPY_BUFFER_BYTES = 1024 * 1024


def validate_local_source(settings: Settings, raw_path: str) -> Path:
    """Confere que o caminho é um arquivo de vídeo utilizável.

    Validação própria, sem reaproveitar os helpers de storage interno: as
    regras aqui são outras (caminho absoluto de qualquer lugar do disco, mas
    somente arquivo regular e dentro dos limites configurados).
    """
    if not raw_path or not raw_path.strip():
        raise InvalidVideoURLError("Nenhum arquivo informado.")

    path = Path(raw_path.strip())
    if not path.is_absolute():
        raise InvalidVideoURLError("Selecione o arquivo pelo seletor do aplicativo.")

    resolved = path.resolve()
    if not resolved.exists():
        raise InvalidVideoURLError("Arquivo não encontrado.")
    if resolved.is_dir():
        raise InvalidVideoURLError("Selecione um arquivo, não uma pasta.")
    if not resolved.is_file():
        raise InvalidVideoURLError("O caminho informado não é um arquivo.")

    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise InvalidVideoURLError("Formato não suportado. Use mp4, mkv, mov, webm, avi ou m4v.")

    size = resolved.stat().st_size
    if size == 0:
        raise InvalidVideoURLError("Arquivo vazio.")
    if size > settings.max_video_file_size_bytes:
        raise VideoTooLargeError("O arquivo é maior que o limite permitido.")

    return resolved


def _copy_in_chunks(source: Path, destination: Path, total: int, report: ProgressCallback) -> None:
    """Cópia em blocos, com progresso por bytes.

    Um arquivo de vídeo não cabe confortavelmente em memória, e a cópia pode
    demorar o bastante para o usuário achar que travou.
    """
    copied = 0
    span = STAGE_PROGRESS[IngestStage.PROBING] - STAGE_PROGRESS[IngestStage.DOWNLOADING]

    with source.open("rb") as origin, destination.open("wb") as copy:
        while True:
            chunk = origin.read(COPY_BUFFER_BYTES)
            if not chunk:
                break
            copy.write(chunk)
            copied += len(chunk)
            if total > 0:
                progress = STAGE_PROGRESS[IngestStage.DOWNLOADING] + int(span * copied / total)
                report(IngestStage.DOWNLOADING, min(progress, STAGE_PROGRESS[IngestStage.PROBING]))


def import_local_file(
    settings: Settings,
    video_id: str,
    raw_path: str,
    *,
    on_progress: ProgressCallback = noop_progress,
) -> VideoSourceInfo:
    """Copia o arquivo para o storage interno e devolve a metadata normalizada.

    O resultado é o mesmo `VideoSourceInfo` da ingestão por URL, então nada
    depois disto precisa saber de onde o vídeo veio.
    """
    from app.services.ingest.service import workspace_for

    source = validate_local_source(settings, raw_path)
    on_progress(IngestStage.STARTING, STAGE_PROGRESS[IngestStage.STARTING])

    # ffprobe antes de copiar: recusar um arquivo de 3 GB depois da cópia seria
    # desperdício de disco e de tempo.
    try:
        probed = probe_file(source, timeout=settings.ffprobe_timeout_seconds)
    except MediaError as exc:
        raise VideoDownloadError("Não foi possível ler este arquivo de vídeo.") from exc

    if not probed.has_video:
        raise VideoDownloadError("O arquivo não contém uma faixa de vídeo.")
    if (
        probed.duration_seconds is not None
        and probed.duration_seconds > settings.max_video_duration_seconds
    ):
        raise VideoTooLongError("O vídeo é mais longo que o limite permitido.")

    workspace = workspace_for(settings, video_id)
    workspace.mkdir(parents=True, exist_ok=True)

    filename = validate_filename(f"source{source.suffix.lower()}")
    destination = workspace / filename

    try:
        _copy_in_chunks(source, destination, source.stat().st_size, on_progress)
    except OSError as exc:
        # Cópia parcial some; o original do usuário não é tocado em momento
        # nenhum.
        destination.unlink(missing_ok=True)
        logger.exception("Falha ao importar arquivo local")
        raise VideoDownloadError("Falha ao copiar o arquivo para o aplicativo.") from exc

    on_progress(IngestStage.FINALIZING, STAGE_PROGRESS[IngestStage.FINALIZING])
    media_info = probe_file(destination, timeout=settings.ffprobe_timeout_seconds)

    info = build_source_info(
        video_id=video_id,
        source_url="",
        provider=LOCAL_PROVIDER,
        local_filename=filename,
        file_size_bytes=destination.stat().st_size,
        info={"title": sanitize_title(source.stem)},
        media_info=media_info,
    )

    on_progress(IngestStage.COMPLETED, STAGE_PROGRESS[IngestStage.COMPLETED])
    return info
