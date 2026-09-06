"""Modelo de vídeo importado."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Enum,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DEFAULT_CLIP_DURATION_SECONDS, DEFAULT_SUBTITLE_FONT_SIZE
from app.db.base import Base, TimestampMixin, new_id
from app.models.enums import DEFAULT_VIDEO_LAYOUT, SourceType, VerticalLayout, VideoStatus

if TYPE_CHECKING:
    from app.models.clip import Clip
    from app.models.job import Job
    from app.models.transcript import Transcript
    from app.schemas.settings import VideoSettings


class Video(Base, TimestampMixin):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)

    # Nulo para vídeo importado do disco: não existe URL a inventar.
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, length=16),
        default=SourceType.REMOTE,
        server_default=SourceType.REMOTE.name,
        nullable=False,
    )
    # Caminho externo escolhido no diálogo nativo, guardado só até a cópia para
    # o storage interno terminar.
    import_path: Mapped[str | None] = mapped_column(String(1024))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_video_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(512))

    duration: Mapped[float | None] = mapped_column()
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column()
    video_codec: Mapped[str | None] = mapped_column(String(64))
    audio_codec: Mapped[str | None] = mapped_column(String(64))
    container: Mapped[str | None] = mapped_column(String(128))
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    # Chave relativa ao storage ({video_id}/source.mp4), nunca caminho absoluto.
    source_file_key: Mapped[str | None] = mapped_column(String(512))

    # Configuração de processamento escolhida na criação, como JSON versionado.
    # Fica no próprio Video: reprocessar um vídeo antigo deve usar o que ele
    # pediu, não o default vigente.
    settings_json: Mapped[dict[str, Any] | None] = mapped_column("settings", JSON)

    # --- legado ---
    # Substituídas por `settings`; mantidas até a remoção ser validada em
    # produção. Continuam sendo escritas para que um rollback do código não
    # perca a configuração.
    clip_duration_seconds: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_CLIP_DURATION_SECONDS, server_default="90", nullable=False
    )
    layout: Mapped[VerticalLayout] = mapped_column(
        Enum(VerticalLayout, native_enum=False, length=32),
        default=DEFAULT_VIDEO_LAYOUT,
        server_default=DEFAULT_VIDEO_LAYOUT.name,
        nullable=False,
    )
    subtitle_font_size: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_SUBTITLE_FONT_SIZE, server_default="72", nullable=False
    )

    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus, native_enum=False, length=32),
        default=VideoStatus.PENDING,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1024))

    @property
    def settings(self) -> VideoSettings:
        """Configuração efetiva do vídeo.

        Sem JSON (registro anterior à coluna), reconstrói a partir das colunas
        legadas; sem elas, cai nos defaults — que reproduzem o comportamento
        que o vídeo teve quando foi criado.
        """
        # Import local: `schemas.settings` depende dos enums de `models`, e o
        # import no topo fecharia o ciclo.
        from app.schemas.settings import VideoSettings

        if self.settings_json is not None:
            return VideoSettings.from_stored(self.settings_json)

        return VideoSettings(
            clip_duration_seconds=self.clip_duration_seconds,
            layout=self.layout,
            subtitle_font_size=self.subtitle_font_size,
        )

    def apply_settings(self, settings: VideoSettings) -> None:
        """Grava o JSON e espelha nas colunas legadas enquanto elas existirem."""
        self.settings_json = settings.model_dump(mode="json")
        self.clip_duration_seconds = settings.clip_duration_seconds
        self.layout = settings.layout
        self.subtitle_font_size = settings.subtitle_font_size

    jobs: Mapped[list[Job]] = relationship(
        back_populates="video", cascade="all, delete-orphan", passive_deletes=True
    )
    clips: Mapped[list[Clip]] = relationship(
        back_populates="video", cascade="all, delete-orphan", passive_deletes=True
    )
    transcript: Mapped[Transcript | None] = relationship(
        back_populates="video", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        CheckConstraint("duration IS NULL OR duration >= 0", name="duration_non_negative"),
        CheckConstraint("file_size IS NULL OR file_size >= 0", name="file_size_non_negative"),
        CheckConstraint("clip_duration_seconds > 0", name="clip_duration_positive"),
        CheckConstraint(
            "subtitle_font_size >= 48 AND subtitle_font_size <= 110",
            name="subtitle_font_size_range",
        ),
        Index("ix_videos_status", "status"),
        Index("ix_videos_created_at", "created_at"),
    )
