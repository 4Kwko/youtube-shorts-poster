"""Decisão de qual etapa refazer quando um vídeo falha.

O retry começa na menor etapa que resolve: um export que falhou não precisa de
novo download, transcrição ou render.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import JobStatus, JobType, VideoStatus
from app.models.job import Job
from app.models.video import Video

# Estado para o qual o vídeo volta quando cada etapa é refeita.
RETRY_VIDEO_STATUS: dict[JobType, VideoStatus] = {
    JobType.INGEST: VideoStatus.QUEUED,
    JobType.TRANSCRIBE: VideoStatus.DOWNLOADED,
    JobType.CLIP: VideoStatus.TRANSCRIBED,
    JobType.RENDER: VideoStatus.CLIPPED,
    JobType.EXPORT: VideoStatus.RENDERED,
}

# Ordem do pipeline, da última para a primeira etapa.
PIPELINE_ORDER: tuple[JobType, ...] = (
    JobType.EXPORT,
    JobType.RENDER,
    JobType.CLIP,
    JobType.TRANSCRIBE,
    JobType.INGEST,
)


@dataclass(frozen=True, slots=True)
class RetryPlan:
    job_type: JobType
    video_status: VideoStatus


def plan_retry(video: Video, jobs: list[Job]) -> RetryPlan:
    """Escolhe a etapa a repetir a partir do último job que falhou.

    Sem job falho registrado, recomeça pela etapa mais avançada que o estado do
    vídeo permite — nunca antes do que já está pronto no disco.
    """
    failed = [job for job in jobs if job.status is JobStatus.FAILED]
    if failed:
        latest = max(failed, key=lambda job: (job.finished_at or job.created_at, job.id))
        if latest.job_type in RETRY_VIDEO_STATUS:
            return RetryPlan(latest.job_type, RETRY_VIDEO_STATUS[latest.job_type])

    if video.settings.output_directory and video.status in {
        VideoStatus.RENDERED,
        VideoStatus.EXPORTING,
        VideoStatus.EXPORTED,
    }:
        return RetryPlan(JobType.EXPORT, VideoStatus.RENDERED)
    if video.status in {VideoStatus.CLIPPED, VideoStatus.PROCESSING}:
        return RetryPlan(JobType.RENDER, VideoStatus.CLIPPED)
    if video.status is VideoStatus.TRANSCRIBED:
        return RetryPlan(JobType.CLIP, VideoStatus.TRANSCRIBED)
    if video.status is VideoStatus.DOWNLOADED and video.source_file_key:
        return RetryPlan(JobType.TRANSCRIBE, VideoStatus.DOWNLOADED)

    return RetryPlan(JobType.INGEST, VideoStatus.QUEUED)
