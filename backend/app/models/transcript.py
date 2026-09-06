"""Metadata da transcrição de um vídeo.

O conteúdo fica em JSON no storage; aqui guardamos só o que precisa ser
consultável e a chave relativa do arquivo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_id

if TYPE_CHECKING:
    from app.models.video import Video


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    video_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )

    language: Mapped[str | None] = mapped_column(String(16))
    language_probability: Mapped[float | None] = mapped_column(Float)
    # Relativa a storage/transcripts, nunca caminho absoluto.
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)

    video: Mapped[Video] = relationship(back_populates="transcript")

    __table_args__ = (
        # 1:1 com Video.
        UniqueConstraint("video_id", name="uq_transcripts_video_id"),
        CheckConstraint(
            "language_probability IS NULL OR (language_probability >= 0 "
            "AND language_probability <= 1)",
            name="language_probability_range",
        ),
    )
