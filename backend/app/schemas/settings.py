"""Configuração de processamento de um vídeo.

Um único objeto versionado, persistido como JSON no `Video`. Adicionar uma
opção nova é acrescentar um campo aqui — sem migration por slider.

Todo campo tem default igual ao comportamento anterior à existência dele, então
um vídeo antigo (ou um payload sem `settings`) continua produzindo o mesmo
resultado.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import (
    BACKGROUND_DARKNESS_DEFAULT,
    BLUR_STRENGTH_DEFAULT,
    CLIP_DURATION_OPTIONS,
    DEFAULT_CLIP_DURATION_SECONDS,
    DEFAULT_SUBTITLE_FONT_SIZE,
    FOREGROUND_SCALE_DEFAULT,
    FOREGROUND_SCALE_MAX,
    FOREGROUND_SCALE_MIN,
    SUBTITLE_FONT_SIZE_MAX,
    SUBTITLE_FONT_SIZE_MIN,
    SUBTITLE_OFFSET_LIMIT,
    VOLUME_DEFAULT,
)
from app.models.enums import (
    DEFAULT_VIDEO_LAYOUT,
    FilenamePattern,
    OutputFps,
    RenderQuality,
    SubtitlePosition,
    SubtitleStylePreset,
    VerticalLayout,
)

SETTINGS_VERSION = 1

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class VideoSettings(BaseModel):
    """Escolhas do usuário para um vídeo. Fixas depois que o job começa."""

    model_config = ConfigDict(extra="forbid")

    version: int = SETTINGS_VERSION

    # --- corte ---
    clip_duration_seconds: int = DEFAULT_CLIP_DURATION_SECONDS

    # --- enquadramento ---
    layout: VerticalLayout = DEFAULT_VIDEO_LAYOUT
    blur_strength: int = Field(default=BLUR_STRENGTH_DEFAULT, ge=0, le=100)
    background_darkness: int = Field(default=BACKGROUND_DARKNESS_DEFAULT, ge=0, le=100)
    # Percentual da largura do canvas ocupada pelo vídeo central.
    foreground_scale: int = Field(
        default=FOREGROUND_SCALE_DEFAULT, ge=FOREGROUND_SCALE_MIN, le=FOREGROUND_SCALE_MAX
    )

    # --- legenda ---
    subtitles_enabled: bool = True
    subtitle_font_size: int = Field(
        default=DEFAULT_SUBTITLE_FONT_SIZE, ge=SUBTITLE_FONT_SIZE_MIN, le=SUBTITLE_FONT_SIZE_MAX
    )
    subtitle_position: SubtitlePosition = SubtitlePosition.BOTTOM
    # Ajuste fino sobre a posição do preset, em pixels na grade 1080x1920.
    subtitle_vertical_offset: int = Field(
        default=0, ge=-SUBTITLE_OFFSET_LIMIT, le=SUBTITLE_OFFSET_LIMIT
    )
    subtitle_style: SubtitleStylePreset = SubtitleStylePreset.BOLD
    subtitle_text_color: str = "#FFFFFF"
    subtitle_outline_color: str = "#000000"

    # --- saída ---
    render_quality: RenderQuality = RenderQuality.BALANCED
    output_fps: OutputFps = OutputFps.ORIGINAL
    volume: int = Field(default=VOLUME_DEFAULT, ge=0, le=100)
    normalize_audio: bool = False

    # --- exportação ---
    # Snapshot das preferências do app no momento da criação: mudar a pasta
    # depois não muda o destino de um vídeo já em processamento.
    # `None` desliga a exportação; os renders ficam só no storage interno.
    output_directory: str | None = Field(default=None, max_length=1024)
    filename_pattern: FilenamePattern = FilenamePattern.CLIP
    open_output_folder: bool = True
    keep_original: bool = True

    @field_validator("clip_duration_seconds")
    @classmethod
    def _must_be_an_offered_duration(cls, value: int) -> int:
        # Valor livre viraria clip de 7 segundos ou de duas horas; a lista é a
        # mesma que a interface mostra.
        if value not in CLIP_DURATION_OPTIONS:
            raise ValueError(
                f"Duração inválida. Opções: {', '.join(str(o) for o in CLIP_DURATION_OPTIONS)}."
            )
        return value

    @field_validator("subtitle_text_color", "subtitle_outline_color")
    @classmethod
    def _must_be_hex_color(cls, value: str) -> str:
        if not _HEX_COLOR.match(value):
            raise ValueError("Cor deve estar no formato #RRGGBB.")
        return value.upper()

    @classmethod
    def from_stored(cls, payload: Any) -> VideoSettings:
        """Lê o JSON persistido, tolerando ausência e formato antigo.

        Vídeo criado antes desta configuração existir não tem `settings`; nesse
        caso os defaults reproduzem exatamente o comportamento anterior.
        """
        if not isinstance(payload, dict):
            return cls()
        # Older projects may have long clips; retain their other render preferences.
        duration = payload.get("clip_duration_seconds")
        if isinstance(duration, (int, float)) and duration > 180:
            payload = {**payload, "clip_duration_seconds": 180}
        try:
            return cls.model_validate(payload)
        except ValueError:
            # JSON de uma versão futura ou corrompido: melhor render com os
            # defaults do que job falhando por configuração.
            return cls()
