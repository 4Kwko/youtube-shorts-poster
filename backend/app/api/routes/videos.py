"""Rotas de vídeos.

A criação apenas registra a intenção: valida a URL, grava `Video` + `Job` e
devolve 202. Nada de yt-dlp, FFmpeg ou espera — quem executa é o worker.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse

from app.api.deps import SessionDep, SettingsDep
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import JobType, VideoStatus
from app.models.video import Video
from app.repositories import (
    ClipRepository,
    JobRepository,
    TranscriptRepository,
    VideoRepository,
)
from app.schemas.clip import ClipResponse
from app.schemas.job import JobResponse
from app.schemas.transcript import TranscriptResponse
from app.schemas.video import (
    LocalImportRequest,
    RetryResponse,
    VideoBatchRequest,
    VideoBatchResponse,
    VideoCreateRequest,
    VideoListResponse,
    VideoResponse,
    VideoSummary,
)
from app.services.cleanup import purge_video_files
from app.services.ingest.local import validate_local_source
from app.services.ingest.metadata import sanitize_title
from app.services.ingest.urls import ValidatedVideoURL, validate_video_url
from app.services.retry import plan_retry
from app.services.thumbnails import thumbnail_path
from app.services.transcription import read_transcript

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"])

INITIAL_STAGE = "queued"


@router.post(
    "",
    response_model=VideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Registra um vídeo e enfileira a importação",
    description="Valida a URL e cria o Video e o Job de ingestão. O download é assíncrono.",
)
def create_video(payload: VideoCreateRequest, session: SessionDep) -> VideoResponse:
    validated = validate_video_url(payload.url)

    # Video e Job na mesma transação da requisição: se a criação do Job falhar,
    # o session_scope da dependência faz rollback e nenhum Video órfão sobra.
    video = VideoRepository(session).create(
        source_url=validated.url,
        provider=validated.provider.name,
        status=VideoStatus.QUEUED,
        settings=payload.settings,
    )
    video.current_stage = INITIAL_STAGE
    JobRepository(session).create(video_id=video.id, job_type=JobType.INGEST)

    logger.info(
        "Vídeo registrado para ingestão",
        extra={"video_id": video.id, "provider": validated.provider.name},
    )
    return VideoResponse.model_validate(video)


@router.post(
    "/batch",
    response_model=VideoBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Registra vários vídeos de uma vez",
    description=(
        "Cada URL vira um projeto com snapshot próprio das configurações. "
        "Uma URL inválida recusa o envio inteiro, antes de criar qualquer registro."
    ),
)
def create_videos(payload: VideoBatchRequest, session: SessionDep) -> VideoBatchResponse:
    # Valida tudo primeiro: um erro de formato não pode deixar metade dos
    # projetos criados.
    validated = [validate_video_url(url) for url in payload.urls]

    # Duplicatas no mesmo envio viram um projeto só; processar a mesma URL duas
    # vezes no mesmo clique é engano, não intenção.
    unique: list[ValidatedVideoURL] = []
    seen: set[str] = set()
    for item in validated:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)

    videos = VideoRepository(session)
    jobs = JobRepository(session)
    created: list[VideoResponse] = []

    for item in unique:
        video = videos.create(
            source_url=item.url,
            provider=item.provider.name,
            status=VideoStatus.QUEUED,
            settings=payload.settings,
        )
        video.current_stage = INITIAL_STAGE
        jobs.create(video_id=video.id, job_type=JobType.INGEST)
        created.append(VideoResponse.model_validate(video))

    logger.info("Lote registrado", extra={"videos": len(created)})
    return VideoBatchResponse(videos=created)


@router.post(
    "/local",
    response_model=VideoBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Registra vídeos a partir de arquivos do disco",
    description=(
        "Os caminhos vêm do seletor nativo do aplicativo. A cópia para o "
        "storage interno acontece no worker; o arquivo original só é lido."
    ),
)
def create_local_videos(
    payload: LocalImportRequest, session: SessionDep, settings: SettingsDep
) -> VideoBatchResponse:
    # Validação estrutural antes de persistir — um caminho ruim recusa o envio
    # inteiro. O ffprobe roda no worker, junto da cópia.
    sources = [validate_local_source(settings, path) for path in payload.paths]

    unique: list[Path] = []
    seen: set[str] = set()
    for source in sources:
        key = str(source)
        if key not in seen:
            seen.add(key)
            unique.append(source)

    videos = VideoRepository(session)
    jobs = JobRepository(session)
    created: list[VideoResponse] = []

    for source in unique:
        video = videos.create_local(
            title=sanitize_title(source.stem) or source.name,
            import_path=str(source),
            settings=payload.settings,
        )
        video.current_stage = INITIAL_STAGE
        jobs.create(video_id=video.id, job_type=JobType.INGEST)
        created.append(VideoResponse.model_validate(video))

    logger.info("Arquivos locais registrados", extra={"videos": len(created)})
    return VideoBatchResponse(videos=created)


@router.get(
    "/{video_id}",
    response_model=VideoResponse,
    summary="Estado de um vídeo",
)
def get_video(video_id: str, session: SessionDep) -> VideoResponse:
    video = VideoRepository(session).get_by_id(video_id)
    if video is None:
        raise NotFoundError("Vídeo não encontrado.")
    return VideoResponse.model_validate(video)


@router.get(
    "/{video_id}/jobs",
    response_model=list[JobResponse],
    summary="Jobs de um vídeo",
    description="Ordenados por data de criação.",
)
def list_video_jobs(video_id: str, session: SessionDep) -> list[JobResponse]:
    if VideoRepository(session).get_by_id(video_id) is None:
        raise NotFoundError("Vídeo não encontrado.")

    jobs = JobRepository(session).list_for_video(video_id)
    return [JobResponse.model_validate(job) for job in jobs]


@router.get(
    "/{video_id}/clips",
    response_model=list[ClipResponse],
    summary="Clips de um vídeo",
    description="Ordenados por sequence. Lista vazia enquanto o clipping não rodou.",
)
def list_video_clips(video_id: str, session: SessionDep) -> list[ClipResponse]:
    if VideoRepository(session).get_by_id(video_id) is None:
        raise NotFoundError("Vídeo não encontrado.")

    clips = ClipRepository(session).list_for_video(video_id)
    return [ClipResponse.model_validate(clip) for clip in clips]


@router.get(
    "/{video_id}/transcript",
    response_model=TranscriptResponse,
    summary="Transcrição de um vídeo",
    description="Segmentos e timestamps por palavra, no eixo do vídeo original.",
)
def get_video_transcript(
    video_id: str, session: SessionDep, settings: SettingsDep
) -> TranscriptResponse:
    if VideoRepository(session).get_by_id(video_id) is None:
        raise NotFoundError("Vídeo não encontrado.")

    transcript = TranscriptRepository(session).get_for_video(video_id)
    if transcript is None:
        raise NotFoundError("Transcrição ainda não disponível.")

    # O conteúdo vive no storage; o banco só aponta para ele.
    result = read_transcript(settings, transcript.file_key)

    return TranscriptResponse(
        video_id=video_id,
        language=result.language,
        language_probability=result.language_probability,
        duration=result.duration,
        segments=result.segments,
    )


def _summary(video: Video, clip_count: int, settings: Settings) -> VideoSummary:
    summary = VideoSummary.model_validate(video)
    return summary.model_copy(
        update={
            "clip_count": clip_count,
            "has_thumbnail": thumbnail_path(settings, video.id).is_file(),
        }
    )


@router.get(
    "",
    response_model=VideoListResponse,
    summary="Lista os projetos",
    description="Mais recentes primeiro. Só resumo: os clips vêm em outra rota.",
)
def list_videos(
    session: SessionDep,
    settings: SettingsDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> VideoListResponse:
    repository = VideoRepository(session)
    rows = repository.list_with_clip_counts(limit=limit, offset=offset)

    return VideoListResponse(
        items=[_summary(video, count, settings) for video, count in rows],
        total=repository.count(),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{video_id}/thumbnail",
    summary="Miniatura do projeto",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "Sem miniatura"}},
)
def get_video_thumbnail(video_id: str, session: SessionDep, settings: SettingsDep) -> FileResponse:
    if VideoRepository(session).get_by_id(video_id) is None:
        raise NotFoundError("Vídeo não encontrado.")

    # O caminho sai do storage helper; o cliente só informa o id.
    path = thumbnail_path(settings, video_id)
    if not path.is_file():
        raise NotFoundError("Miniatura ainda não disponível.")

    return FileResponse(path, media_type="image/jpeg")


@router.post(
    "/{video_id}/retry",
    response_model=RetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Refaz a menor etapa necessária",
)
def retry_video(video_id: str, session: SessionDep) -> RetryResponse:
    videos = VideoRepository(session)
    video = videos.get_by_id(video_id)
    if video is None:
        raise NotFoundError("Vídeo não encontrado.")

    jobs = JobRepository(session)
    if any(jobs.has_pending(video_id, job_type) for job_type in JobType):
        raise ConflictError("Este projeto já tem uma etapa em andamento.")

    # O backend decide a etapa: o frontend não conhece a ordem do pipeline.
    plan = plan_retry(video, list(jobs.list_for_video(video_id)))
    job = jobs.create(video_id=video_id, job_type=plan.job_type)
    videos.update_status(video_id, plan.video_status, progress=0, current_stage="retry")
    video.error_code = None
    video.error_message = None

    logger.info(
        "Retry solicitado",
        extra={"video_id": video_id, "job_type": plan.job_type.value},
    )
    return RetryResponse(
        video_id=video_id, job_id=job.id, job_type=plan.job_type, status=plan.video_status
    )


@router.delete(
    "/{video_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Exclui o projeto e seus arquivos internos",
    description="Os clips já exportados para a pasta do usuário são preservados.",
)
def delete_video(video_id: str, session: SessionDep, settings: SettingsDep) -> Response:
    videos = VideoRepository(session)
    if videos.get_by_id(video_id) is None:
        raise NotFoundError("Vídeo não encontrado.")

    # Arquivos primeiro: se a limpeza falhar, o registro continua no banco e o
    # projeto pode ser excluído de novo. O inverso deixaria lixo órfão.
    removed = purge_video_files(settings, video_id)
    videos.delete(video_id)

    logger.info("Projeto excluído", extra={"video_id": video_id, "removed_dirs": removed})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
