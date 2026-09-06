"""Acesso a dados de Video. Sem regra de negócio e sem commit."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.clip import Clip
from app.models.enums import SourceType, VideoStatus
from app.models.video import Video
from app.schemas.settings import VideoSettings
from app.services.ingest.local import LOCAL_PROVIDER


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Metadata técnica de um vídeo já importado."""

    title: str | None = None
    provider_video_id: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str | None = None
    file_size: int | None = None
    source_file_key: str | None = None


class VideoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_local(
        self,
        *,
        title: str,
        import_path: str,
        settings: VideoSettings | None = None,
    ) -> Video:
        """Projeto a partir de um arquivo do disco.

        `source_url` fica nulo: não há URL a inventar. O caminho externo é
        guardado só até a cópia interna terminar.
        """
        video = Video(
            source_url=None,
            source_type=SourceType.LOCAL,
            provider=LOCAL_PROVIDER,
            status=VideoStatus.QUEUED,
            title=title,
            import_path=import_path,
        )
        video.apply_settings(settings or VideoSettings())
        self._session.add(video)
        self._session.flush()
        return video

    def create(
        self,
        *,
        source_url: str,
        provider: str,
        provider_video_id: str | None = None,
        status: VideoStatus = VideoStatus.PENDING,
        video_id: str | None = None,
        settings: VideoSettings | None = None,
    ) -> Video:
        video = Video(
            source_url=source_url,
            provider=provider,
            provider_video_id=provider_video_id,
            status=status,
        )
        video.apply_settings(settings or VideoSettings())
        if video_id is not None:
            video.id = video_id
        self._session.add(video)
        self._session.flush()
        return video

    def get_by_id(self, video_id: str) -> Video | None:
        return self._session.get(Video, video_id)

    def _require(self, video_id: str) -> Video:
        video = self.get_by_id(video_id)
        if video is None:
            raise NotFoundError("Vídeo não encontrado.")
        return video

    def update_status(
        self,
        video_id: str,
        status: VideoStatus,
        *,
        progress: int | None = None,
        current_stage: str | None = None,
    ) -> Video:
        video = self._require(video_id)
        video.status = status
        if progress is not None:
            video.progress = progress
        if current_stage is not None:
            video.current_stage = current_stage
        self._session.flush()
        return video

    def update_metadata(self, video_id: str, metadata: VideoMetadata) -> Video:
        video = self._require(video_id)
        for field, value in asdict(metadata).items():
            if value is not None:
                setattr(video, field, value)
        self._session.flush()
        return video

    def mark_failed(self, video_id: str, error_code: str, error_message: str) -> Video:
        video = self._require(video_id)
        video.status = VideoStatus.FAILED
        video.error_code = error_code
        video.error_message = error_message
        self._session.flush()
        return video

    def list_with_clip_counts(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[tuple[Video, int]]:
        """Vídeos mais recentes primeiro, com a contagem de clips junto.

        LEFT JOIN agregado: uma query para a página inteira, em vez de uma
        contagem por vídeo.
        """
        clip_count = func.count(Clip.id).label("clip_count")
        stmt = (
            select(Video, clip_count)
            .outerjoin(Clip, Clip.video_id == Video.id)
            .group_by(Video.id)
            .order_by(Video.created_at.desc(), Video.id)
            .limit(limit)
            .offset(offset)
        )
        return [(row[0], row[1]) for row in self._session.execute(stmt).all()]

    def count(self) -> int:
        total = self._session.execute(select(func.count(Video.id))).scalar_one()
        return int(total)

    def delete(self, video_id: str) -> None:
        """Remove o vídeo; jobs, clips e transcript saem por cascade."""
        self._session.delete(self._require(video_id))
        self._session.flush()

    def list(
        self,
        *,
        status: VideoStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Video]:
        stmt = select(Video).order_by(Video.created_at.desc(), Video.id)
        if status is not None:
            stmt = stmt.where(Video.status == status)
        stmt = stmt.limit(limit).offset(offset)
        return self._session.execute(stmt).scalars().all()
