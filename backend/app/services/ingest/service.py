"""Orquestração da ingestão de vídeo.

Sequência: valida a URL, gera o identificador interno, recusa pelo que já se
sabe antes de gastar banda, baixa, confere o que realmente chegou ao disco e
só então normaliza a metadata.

Qualquer falha depois da criação do workspace remove o diretório: não deixamos
download parcial ocupando storage.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.ingest import VideoSourceInfo
from app.schemas.media import MediaInfo
from app.services.ingest.downloader import DownloaderFactory
from app.services.ingest.errors import (
    LiveStreamNotSupportedError,
    VideoDownloadError,
    VideoTooLargeError,
    VideoTooLongError,
)
from app.services.ingest.metadata import build_source_info, extract_preflight
from app.services.ingest.progress import (
    STAGE_PROGRESS,
    IngestStage,
    ProgressCallback,
    noop_progress,
)
from app.services.ingest.urls import ValidatedVideoURL, validate_video_url
from app.services.ingest.ytdlp import SOURCE_STEM, create_downloader
from app.services.media.errors import MediaError
from app.services.media.probe import probe_file
from app.utils.paths import is_inside, resolve_storage_path, validate_filename

logger = logging.getLogger(__name__)

DOWNLOADS_SUBDIR = "downloads"

# Sufixos que o yt-dlp deixa para trás em download interrompido.
_TEMP_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")


def new_video_id() -> str:
    """Identificador interno imprevisível, sem relação com dado externo."""
    return uuid.uuid4().hex


def workspace_for(settings: Settings, video_id: str) -> Path:
    """Diretório do vídeo dentro do storage.

    `video_id` passa pela mesma validação de nome de arquivo do resto do
    projeto, mesmo sendo gerado internamente: se algum dia vier de fora, a
    barreira já está no caminho.
    """
    return resolve_storage_path(settings, DOWNLOADS_SUBDIR, video_id)


def _cleanup(workspace: Path) -> None:
    if not workspace.exists():
        return
    try:
        shutil.rmtree(workspace)
    except OSError:
        # Storage órfão é ruim, mas mascarar o erro original seria pior.
        logger.exception("Falha ao limpar workspace após erro de ingestão")


def _is_temp_artifact(path: Path) -> bool:
    return path.name.endswith(_TEMP_SUFFIXES)


def _locate_downloaded_file(workspace: Path, info: dict[str, Any]) -> Path | None:
    """Encontra o arquivo final dentro do workspace.

    O caminho anunciado pelo yt-dlp é tratado como dado não confiável: só é
    aceito se cair dentro do workspace. Caso contrário caímos na varredura do
    diretório, que por construção não pode escapar.
    """
    requested = info.get("requested_downloads")
    if isinstance(requested, list):
        for entry in requested:
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("filepath") or entry.get("_filename")
            if not isinstance(raw_path, str) or not raw_path:
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = workspace / candidate
            if not is_inside(workspace, candidate):
                logger.warning("yt-dlp reportou caminho fora do workspace; ignorado")
                continue
            if candidate.is_file() and not _is_temp_artifact(candidate):
                return candidate

    matches = [
        path
        for path in sorted(workspace.glob(f"{SOURCE_STEM}.*"))
        if path.is_file() and not _is_temp_artifact(path)
    ]
    if not matches:
        return None

    # Mais de um arquivo significa restos de faixas separadas; o merge final é
    # sempre o maior.
    return max(matches, key=lambda path: path.stat().st_size)


def _preflight_checks(settings: Settings, info: dict[str, Any]) -> None:
    preflight = extract_preflight(info)

    if preflight.is_live:
        raise LiveStreamNotSupportedError("Transmissões ao vivo não podem ser importadas.")

    if (
        preflight.duration_seconds is not None
        and preflight.duration_seconds > settings.max_video_duration_seconds
    ):
        logger.info(
            "Vídeo recusado por duração",
            extra={
                "duration_seconds": preflight.duration_seconds,
                "limit_seconds": settings.max_video_duration_seconds,
            },
        )
        raise VideoTooLongError("O vídeo é mais longo que o limite permitido.")

    if (
        preflight.estimated_size_bytes is not None
        and preflight.estimated_size_bytes > settings.max_video_file_size_bytes
    ):
        raise VideoTooLargeError("O vídeo é maior que o limite permitido.")


def _probe_downloaded(settings: Settings, path: Path) -> MediaInfo | None:
    """Metadata real do arquivo. Falha aqui não invalida a importação."""
    try:
        return probe_file(path, timeout=settings.ffprobe_timeout_seconds)
    except MediaError:
        logger.warning("Não foi possível analisar o arquivo importado com o ffprobe")
        return None


def import_video(
    settings: Settings,
    raw_url: str,
    *,
    downloader_factory: DownloaderFactory = create_downloader,
    on_progress: ProgressCallback = noop_progress,
) -> VideoSourceInfo:
    """Importa um vídeo por URL para o storage interno.

    Levanta subclasses de `IngestError`; nenhuma exceção do yt-dlp escapa.
    """
    validated: ValidatedVideoURL = validate_video_url(raw_url)
    video_id = new_video_id()
    workspace = workspace_for(settings, video_id)

    logger.info(
        "Iniciando importação",
        extra={
            "video_id": video_id,
            "provider": validated.provider.name,
            "playlist_params_removed": validated.had_playlist_params,
        },
    )

    workspace.mkdir(parents=True, exist_ok=False)

    def report(stage: IngestStage) -> None:
        on_progress(stage, STAGE_PROGRESS[stage])

    try:
        report(IngestStage.STARTING)
        downloader = downloader_factory(settings, validated, workspace)

        _preflight_checks(settings, downloader.preflight())

        report(IngestStage.DOWNLOADING)
        info = downloader.download()

        report(IngestStage.PROBING)

        path = _locate_downloaded_file(workspace, info)
        if path is None:
            # yt-dlp pode retornar sucesso e ainda assim não deixar arquivo
            # utilizável (merge falho, formato só-metadata).
            logger.error(
                "Download reportou sucesso sem arquivo final", extra={"video_id": video_id}
            )
            raise VideoDownloadError("O download não produziu um arquivo utilizável.")

        size = path.stat().st_size
        if size == 0:
            raise VideoDownloadError("O download produziu um arquivo vazio.")

        # A metadata prévia é uma estimativa; o limite real é o do disco.
        if size > settings.max_video_file_size_bytes:
            logger.info(
                "Vídeo recusado por tamanho após download",
                extra={
                    "video_id": video_id,
                    "size_bytes": size,
                    "limit_bytes": settings.max_video_file_size_bytes,
                },
            )
            raise VideoTooLargeError("O vídeo é maior que o limite permitido.")

        local_filename = validate_filename(path.name)
        media_info = _probe_downloaded(settings, path)

        report(IngestStage.FINALIZING)

        source_info = build_source_info(
            video_id=video_id,
            source_url=validated.url,
            provider=validated.provider.name,
            local_filename=local_filename,
            file_size_bytes=size,
            info=info,
            media_info=media_info,
        )
    except Exception:
        _cleanup(workspace)
        raise

    report(IngestStage.COMPLETED)
    logger.info(
        "Importação concluída",
        extra={
            "video_id": video_id,
            "provider": source_info.provider,
            "size_bytes": size,
            "duration_seconds": source_info.duration_seconds,
        },
    )
    return source_info
