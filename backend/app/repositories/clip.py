"""Acesso a dados de Clip. Sem regra de negócio e sem commit."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.clip import Clip
from app.models.enums import ClipStatus


class ClipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        video_id: str,
        sequence: int,
        start_time: float,
        end_time: float,
        status: ClipStatus = ClipStatus.PENDING,
        source_file_key: str | None = None,
    ) -> Clip:
        clip = Clip(
            video_id=video_id,
            sequence=sequence,
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
            status=status,
            source_file_key=source_file_key,
        )
        self._session.add(clip)
        self._session.flush()
        return clip

    def get_by_id(self, clip_id: str) -> Clip | None:
        return self._session.get(Clip, clip_id)

    def delete_for_video(self, video_id: str) -> int:
        """Remove os clips de um vídeo. Usado para reexecutar o job sem duplicar."""
        stmt = delete(Clip).where(Clip.video_id == video_id)
        result = cast(CursorResult[Any], self._session.execute(stmt))
        self._session.flush()
        return result.rowcount

    def _require(self, clip_id: str) -> Clip:
        clip = self.get_by_id(clip_id)
        if clip is None:
            raise NotFoundError("Clip não encontrado.")
        return clip

    def update_status(self, clip_id: str, status: ClipStatus) -> Clip:
        clip = self._require(clip_id)
        clip.status = status
        self._session.flush()
        return clip

    def mark_rendered(self, clip_id: str, rendered_file_key: str) -> Clip:
        clip = self._require(clip_id)
        clip.status = ClipStatus.RENDERED
        clip.rendered_file_key = rendered_file_key
        self._session.flush()
        return clip

    def list_for_video(self, video_id: str) -> Sequence[Clip]:
        stmt = select(Clip).where(Clip.video_id == video_id).order_by(Clip.sequence)
        return self._session.execute(stmt).scalars().all()
