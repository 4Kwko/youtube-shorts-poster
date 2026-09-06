"""Modelo de job de processamento."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_id
from app.models.enums import JobStatus, JobType

if TYPE_CHECKING:
    from app.models.video import Video


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    video_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )

    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, native_enum=False, length=32), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32),
        default=JobStatus.QUEUED,
        nullable=False,
    )

    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1024))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    video: Mapped[Video] = relationship(back_populates="jobs")

    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        CheckConstraint("attempt >= 0", name="attempt_non_negative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        Index("ix_jobs_video_id", "video_id"),
        Index("ix_jobs_status", "status"),
    )
