"""Modelo de clip derivado de um vídeo."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_id
from app.models.enums import ClipStatus

if TYPE_CHECKING:
    from app.models.video import Video


class Clip(Base, TimestampMixin):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    video_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )

    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(nullable=False)
    end_time: Mapped[float] = mapped_column(nullable=False)
    # Redundante em relação a end - start, mas materializado para ordenar e
    # filtrar sem expressão em toda query.
    duration: Mapped[float] = mapped_column(nullable=False)

    status: Mapped[ClipStatus] = mapped_column(
        Enum(ClipStatus, native_enum=False, length=32),
        default=ClipStatus.PENDING,
        nullable=False,
    )
    source_file_key: Mapped[str | None] = mapped_column(String(512))
    rendered_file_key: Mapped[str | None] = mapped_column(String(512))

    video: Mapped[Video] = relationship(back_populates="clips")

    __table_args__ = (
        CheckConstraint("sequence >= 0", name="sequence_non_negative"),
        CheckConstraint("start_time >= 0", name="start_time_non_negative"),
        CheckConstraint("end_time > start_time", name="end_after_start"),
        CheckConstraint("duration > 0", name="duration_positive"),
        UniqueConstraint("video_id", "sequence", name="uq_clips_video_id_sequence"),
        Index("ix_clips_video_id", "video_id"),
    )
