"""Handlers de job e registry de dispatch.

Nenhum handler conhece yt-dlp: a ingestão é acionada pelo `IngestService`, que
já isola o downloader.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app.core.errors import AppError
from app.db.session import session_scope
from app.jobs.context import JobContext
from app.models.enums import ClipStatus, JobType, SourceType, VideoStatus
from app.repositories import (
    ClipRepository,
    JobRepository,
    TranscriptRepository,
    VideoRepository,
    video_metadata_from_source,
)
from app.schemas.settings import VideoSettings
from app.schemas.transcript import TranscriptResult
from app.services.clipping import compute_intervals
from app.services.clipping.errors import ClipSourceUnavailableError
from app.services.export import export_clips, validate_output_directory
from app.services.export.errors import ExportFailedError, InvalidOutputDirectoryError
from app.services.ingest.errors import InvalidVideoURLError
from app.services.ingest.local import import_local_file
from app.services.ingest.progress import IngestStage
from app.services.ingest.service import DOWNLOADS_SUBDIR, import_video
from app.services.rendering import VerticalRenderer
from app.services.rendering.errors import RenderSourceUnavailableError
from app.services.rendering.storage import RENDERS_SUBDIR
from app.services.subtitles import (
    build_ass,
    build_events,
    get_style,
    slice_transcript,
    write_subtitle,
)
from app.services.thumbnails import generate_thumbnail
from app.services.transcription import (
    delete_transcript,
    read_transcript,
    transcribe_file,
    write_transcript,
)
from app.services.transcription.errors import TranscriptionFailedError
from app.utils.paths import is_inside, resolve_storage_path

logger = logging.getLogger(__name__)

JobHandler = Callable[[JobContext], None]


class UnknownJobTypeError(AppError):
    """Job com tipo sem handler registrado."""

    status_code = 500
    code = "unknown_job_type"


def _record_progress(context: JobContext, stage: IngestStage, progress: int) -> None:
    """Persiste progresso em transação própria e curta."""
    with session_scope(context.session_factory) as session:
        VideoRepository(session).update_status(
            context.video_id,
            VideoStatus.DOWNLOADING,
            progress=progress,
            current_stage=stage.value,
        )


def handle_ingest(context: JobContext) -> None:
    """Traz o vídeo para o storage interno.

    Duas origens, um resultado: URL passa pelo `IngestService` e arquivo local
    é copiado do disco. As duas devolvem o mesmo `VideoSourceInfo`, então nada
    depois desta etapa sabe de onde o vídeo veio.
    """
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        if video is None:
            raise UnknownJobTypeError("Vídeo do job não existe mais.", code="video_not_found")
        source_type = video.source_type
        source_url = video.source_url
        import_path = video.import_path

    def on_progress(stage: IngestStage, progress: int) -> None:
        _record_progress(context, stage, progress)

    if source_type is SourceType.LOCAL:
        if not import_path:
            raise InvalidVideoURLError("O arquivo original não está mais disponível.")
        info = import_local_file(
            context.settings, context.video_id, import_path, on_progress=on_progress
        )
    else:
        if not source_url:
            raise InvalidVideoURLError("Vídeo sem URL de origem.")
        info = import_video(context.settings, source_url, on_progress=on_progress)

    # Metadata, status e o próximo job na mesma transação: não existe estado
    # em que a ingestão terminou mas o clipping nunca foi enfileirado.
    with session_scope(context.session_factory) as session:
        repo = VideoRepository(session)
        repo.update_metadata(context.video_id, video_metadata_from_source(info))
        repo.update_status(
            context.video_id,
            VideoStatus.DOWNLOADED,
            progress=100,
            current_stage=IngestStage.COMPLETED.value,
        )
        stored = repo.get_by_id(context.video_id)
        if stored is not None:
            # A cópia interna existe: o caminho externo não é mais necessário.
            stored.import_path = None
            if info.title and not stored.title:
                stored.title = info.title
        next_job = JobRepository(session).create_if_absent(
            video_id=context.video_id, job_type=JobType.TRANSCRIBE
        )

    logger.info(
        "Ingestão concluída pelo worker",
        extra={
            "job_id": context.job_id,
            "video_id": context.video_id,
            "source_type": source_type.value,
            "next_job_id": next_job.id if next_job else None,
        },
    )


def handle_transcribe(context: JobContext) -> None:
    """Transcreve o vídeo original uma única vez, com timestamps por palavra.

    A transcrição é do original, não dos clips: um único encode de áudio e
    timestamps já no eixo do vídeo inteiro, que é o que as legendas por clip
    vão precisar.
    """
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        if video is None or not video.source_file_key:
            raise TranscriptionFailedError("Vídeo de origem indisponível.")
        source_key = video.source_file_key
        VideoRepository(session).update_status(
            context.video_id,
            VideoStatus.TRANSCRIBING,
            progress=0,
            current_stage="transcribing",
        )

    source = resolve_storage_path(context.settings, DOWNLOADS_SUBDIR, *source_key.split("/"))

    try:
        result = transcribe_file(context.settings, source)
        file_key = write_transcript(context.settings, context.video_id, result)
    except Exception:
        # JSON parcial é pior que JSON ausente: o retry precisa começar limpo.
        delete_transcript(context.settings, context.video_id)
        raise

    with session_scope(context.session_factory) as session:
        TranscriptRepository(session).upsert(
            video_id=context.video_id,
            file_key=file_key,
            language=result.language,
            language_probability=result.language_probability,
        )
        VideoRepository(session).update_status(
            context.video_id,
            VideoStatus.TRANSCRIBED,
            progress=100,
            current_stage="transcribed",
        )
        JobRepository(session).create_if_absent(video_id=context.video_id, job_type=JobType.CLIP)

    logger.info(
        "Transcrição concluída",
        extra={
            "video_id": context.video_id,
            "language": result.language,
            "segments": len(result.segments),
        },
    )


# Mantido para intermediários opcionais (FixedClipper); o pipeline padrão não
# escreve mais aqui.
CLIPS_SUBDIR = "clips"


def handle_clip(context: JobContext) -> None:
    """Calcula os intervalos e cria os registros de Clip.

    Etapa puramente lógica: nenhum arquivo é gerado aqui. O corte acontece
    junto com a conversão vertical, numa única passagem de FFmpeg por clip —
    gerar um clip horizontal intermediário significaria encodar tudo duas
    vezes.
    """
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        if video is None:
            raise ClipSourceUnavailableError("Vídeo do job não existe mais.")
        if not video.source_file_key or video.duration is None:
            raise ClipSourceUnavailableError("Vídeo ainda não foi importado.")
        duration = video.duration
        # Configuração escolhida na criação do vídeo, não o default vigente.
        clip_duration = video.settings.clip_duration_seconds

    intervals = compute_intervals(duration, clip_duration)

    # Registros, status e o próximo job na mesma transação: ou o vídeo tem o
    # conjunto completo de clips, ou nenhum.
    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session)
        removed = clips.delete_for_video(context.video_id)
        for interval in intervals:
            clips.create(
                video_id=context.video_id,
                sequence=interval.sequence,
                start_time=interval.start_time,
                end_time=interval.end_time,
                status=ClipStatus.PENDING,
            )
        VideoRepository(session).update_status(
            context.video_id, VideoStatus.CLIPPED, progress=100, current_stage="clipped"
        )
        JobRepository(session).create_if_absent(video_id=context.video_id, job_type=JobType.RENDER)

    if removed:
        logger.info(
            "Clips de tentativa anterior descartados",
            extra={"video_id": context.video_id, "count": removed},
        )
    logger.info(
        "Intervalos calculados",
        extra={"video_id": context.video_id, "clips": len(intervals)},
    )


def _prepare_subtitles(
    context: JobContext,
    transcript: TranscriptResult | None,
    sequence: int,
    start_time: float,
    end_time: float,
    settings: VideoSettings,
) -> Path | None:
    """Gera o `.ass` do clip.

    `None` quando não há transcrição, não há fala no intervalo ou a legenda foi
    desligada — nesse caso nenhum arquivo é escrito e o filtro nem entra no
    filtergraph.
    """
    if transcript is None or not settings.subtitles_enabled:
        return None

    local = slice_transcript(transcript, start_time, end_time)
    events = build_events(
        local,
        max_words=context.settings.subtitle_max_words,
        max_chars=context.settings.subtitle_max_chars,
        min_duration=context.settings.subtitle_min_duration_seconds,
        max_duration=context.settings.subtitle_max_duration_seconds,
        pause_break=context.settings.subtitle_pause_break_seconds,
    )
    if not events:
        return None

    # Regenerável a partir do transcript: sobrescrever é sempre seguro.
    style = get_style(
        settings.subtitle_style.value,
        font_size=settings.subtitle_font_size,
        position=settings.subtitle_position,
        vertical_offset=settings.subtitle_vertical_offset,
        text_color=settings.subtitle_text_color,
        outline_color=settings.subtitle_outline_color,
    )
    content = build_ass(events, style=style)
    return write_subtitle(context.settings, context.video_id, sequence, content)


def _render_clip(
    context: JobContext,
    clip_id: str,
    source: Path,
    sequence: int,
    start_time: float,
    duration: float,
    subtitles: Path | None,
    source_size: tuple[int, int] | None,
    settings: VideoSettings,
) -> str:
    """Renderiza um intervalo do vídeo original e devolve a chave relativa."""
    filename = f"{sequence:03d}.mp4"
    output = resolve_storage_path(context.settings, RENDERS_SUBDIR, context.video_id, filename)

    with session_scope(context.session_factory) as session:
        ClipRepository(session).update_status(clip_id, ClipStatus.RENDERING)

    try:
        VerticalRenderer(context.settings).render(
            source,
            output,
            start_time=start_time,
            duration=duration,
            subtitles=subtitles,
            source_size=source_size,
            settings=settings,
        )
    except Exception:
        with session_scope(context.session_factory) as session:
            ClipRepository(session).update_status(clip_id, ClipStatus.FAILED)
        raise

    return f"{context.video_id}/{filename}"


def handle_render(context: JobContext) -> None:
    """Renderiza cada clip em 9:16, cortando direto do vídeo original.

    Corte, enquadramento e burn-in da legenda acontecem no mesmo filtergraph:
    uma passagem de FFmpeg por clip.

    Reexecutável: o nome do arquivo de saída vem do `sequence`, então um retry
    sobrescreve deterministicamente. Clips já renderizados cujo arquivo ainda
    existe são pulados, para que o retry termine o que falta.
    """
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        if video is None or not video.source_file_key:
            raise RenderSourceUnavailableError("Vídeo de origem indisponível.")
        source_key = video.source_file_key
        settings = video.settings
        # Dimensões já conhecidas pelo ffprobe da ingestão: evita um probe por
        # clip só para decidir o enquadramento.
        source_size = (
            (video.width, video.height)
            if video.width is not None and video.height is not None
            else None
        )

        clips = [
            (
                clip.id,
                clip.sequence,
                clip.start_time,
                clip.end_time,
                clip.duration,
                clip.rendered_file_key,
                clip.status,
            )
            for clip in ClipRepository(session).list_for_video(context.video_id)
        ]
        transcript_row = TranscriptRepository(session).get_for_video(context.video_id)
        transcript_key = transcript_row.file_key if transcript_row else None
        VideoRepository(session).update_status(
            context.video_id, VideoStatus.PROCESSING, progress=0, current_stage="rendering"
        )

    if not clips:
        raise RenderSourceUnavailableError("O vídeo não possui clips para renderizar.")

    source = resolve_storage_path(context.settings, DOWNLOADS_SUBDIR, *source_key.split("/"))
    # Uma leitura do JSON para o vídeo inteiro; o recorte por clip é em memória.
    transcript = read_transcript(context.settings, transcript_key) if transcript_key else None
    total = len(clips)

    for done, (
        clip_id,
        sequence,
        start_time,
        end_time,
        duration,
        rendered_key,
        status,
    ) in enumerate(clips, start=1):
        already_done = (
            status is ClipStatus.RENDERED
            and rendered_key is not None
            and resolve_storage_path(
                context.settings, RENDERS_SUBDIR, *rendered_key.split("/")
            ).is_file()
        )

        if not already_done:
            subtitles = _prepare_subtitles(
                context, transcript, sequence, start_time, end_time, settings
            )
            key = _render_clip(
                context,
                clip_id,
                source,
                sequence,
                start_time,
                duration,
                subtitles,
                source_size,
                settings,
            )
            with session_scope(context.session_factory) as session:
                ClipRepository(session).mark_rendered(clip_id, key)

        progress = int(done * 100 / total)
        with session_scope(context.session_factory) as session:
            VideoRepository(session).update_status(
                context.video_id,
                VideoStatus.PROCESSING,
                progress=progress,
                current_stage=f"rendering {done}/{total}",
            )
            JobRepository(session).update_progress(context.job_id, progress)

    _generate_project_thumbnail(context)

    if context.settings.youtube_auto_publish:
        from app.services.youtube import enqueue

        with session_scope(context.session_factory) as session:
            video = VideoRepository(session).get_by_id(context.video_id)
            if video is not None:
                for clip in ClipRepository(session).list_for_video(context.video_id):
                    if clip.rendered_file_key:
                        enqueue(
                            context.settings, clip.id,
                            resolve_storage_path(context.settings, RENDERS_SUBDIR,
                                                 *clip.rendered_file_key.split("/")),
                            f"{(video.title or 'SignalCut')[:75]} - Part {clip.sequence + 1}",
                            video.source_url or "",
                        )

    with session_scope(context.session_factory) as session:
        VideoRepository(session).update_status(
            context.video_id, VideoStatus.RENDERED, progress=100, current_stage="rendered"
        )
        # Sem pasta escolhida não há o que exportar: os renders ficam só no
        # storage interno e o vídeo termina em `rendered`.
        if settings.output_directory:
            JobRepository(session).create_if_absent(
                video_id=context.video_id, job_type=JobType.EXPORT
            )

    logger.info("Renderização concluída", extra={"video_id": context.video_id, "clips": total})


def _generate_project_thumbnail(context: JobContext) -> None:
    """Miniatura do projeto, a partir do primeiro clip renderizado."""
    with session_scope(context.session_factory) as session:
        clips = ClipRepository(session).list_for_video(context.video_id)
        first = next((clip for clip in clips if clip.rendered_file_key), None)
        rendered_key = first.rendered_file_key if first else None

    if not rendered_key:
        return

    source = resolve_storage_path(context.settings, RENDERS_SUBDIR, *rendered_key.split("/"))
    generate_thumbnail(context.settings, context.video_id, source)


def _delete_source_file(context: JobContext, source_key: str) -> bool:
    """Apaga o vídeo original importado, com as verificações de segurança.

    Só remove um arquivo que resolve dentro do storage interno de downloads e
    que corresponde ao `source_file_key` do próprio vídeo. Qualquer dúvida
    (chave estranha, arquivo fora do storage) e nada é apagado.
    """
    try:
        path = resolve_storage_path(context.settings, DOWNLOADS_SUBDIR, *source_key.split("/"))
    except ValueError:
        logger.warning("source_file_key inválido; original preservado")
        return False

    downloads_root = context.settings.storage_path(DOWNLOADS_SUBDIR)
    if not is_inside(downloads_root, path) or not path.is_file():
        logger.warning("Original fora do storage interno; nada foi apagado")
        return False

    try:
        path.unlink()
    except OSError:
        logger.exception("Falha ao apagar o vídeo original")
        return False

    return True


def handle_export(context: JobContext) -> None:
    """Copia os renders finais para a pasta escolhida pelo usuário.

    Roda depois de o vídeo inteiro estar renderizado. Falha aqui não toca nos
    renders internos, então o retry recomeça na cópia — sem novo download,
    transcrição ou render.
    """
    with session_scope(context.session_factory) as session:
        video = VideoRepository(session).get_by_id(context.video_id)
        if video is None:
            raise ExportFailedError("Vídeo do job não existe mais.")
        settings = video.settings
        title = video.title
        source_key = video.source_file_key
        clips = [
            (clip.sequence, clip.rendered_file_key)
            for clip in ClipRepository(session).list_for_video(context.video_id)
        ]

    if not settings.output_directory:
        raise InvalidOutputDirectoryError("Nenhuma pasta de saída definida.")
    if not clips:
        raise ExportFailedError("O vídeo não possui clips renderizados.")

    destination = validate_output_directory(settings.output_directory)

    sources: list[tuple[int, Path]] = []
    for sequence, rendered_key in clips:
        if not rendered_key:
            raise ExportFailedError("Há clips sem render concluído.")
        sources.append(
            (
                sequence,
                resolve_storage_path(context.settings, RENDERS_SUBDIR, *rendered_key.split("/")),
            )
        )

    with session_scope(context.session_factory) as session:
        VideoRepository(session).update_status(
            context.video_id, VideoStatus.EXPORTING, progress=0, current_stage="exporting"
        )

    exported = export_clips(sources, destination, pattern=settings.filename_pattern, title=title)

    # Só depois de tudo copiado o original pode sair.
    should_delete = not settings.keep_original and bool(source_key)
    if should_delete and source_key and _delete_source_file(context, source_key):
        with session_scope(context.session_factory) as session:
            video = VideoRepository(session).get_by_id(context.video_id)
            if video is not None:
                # Re-render futuro vai exigir novo download.
                video.source_file_key = None
        logger.info("Vídeo original removido", extra={"video_id": context.video_id})

    with session_scope(context.session_factory) as session:
        VideoRepository(session).update_status(
            context.video_id, VideoStatus.EXPORTED, progress=100, current_stage="exported"
        )

    logger.info(
        "Exportação concluída",
        extra={"video_id": context.video_id, "clips": len(exported)},
    )


HANDLERS: dict[JobType, JobHandler] = {
    JobType.INGEST: handle_ingest,
    JobType.TRANSCRIBE: handle_transcribe,
    JobType.CLIP: handle_clip,
    JobType.RENDER: handle_render,
    JobType.EXPORT: handle_export,
}


def get_handler(job_type: JobType) -> JobHandler:
    handler = HANDLERS.get(job_type)
    if handler is None:
        raise UnknownJobTypeError(f"Nenhum handler implementado para '{job_type.value}'.")
    return handler
