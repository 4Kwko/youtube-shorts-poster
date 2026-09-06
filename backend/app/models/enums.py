"""Enums do domínio. Nenhuma string de status deve existir fora daqui."""

from __future__ import annotations

from enum import StrEnum


class VideoStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    PROCESSING = "processing"
    # Clips gerados; ainda faltam transcrição e renderização para `COMPLETED`.
    CLIPPED = "clipped"
    # Clips já em 9:16; falta transcrição/legendas para `COMPLETED`.
    RENDERED = "rendered"
    EXPORTING = "exporting"
    # Arquivos já na pasta escolhida pelo usuário.
    EXPORTED = "exported"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    INGEST = "ingest"
    TRANSCRIBE = "transcribe"
    CLIP = "clip"
    RENDER = "render"
    EXPORT = "export"
    FULL_PIPELINE = "full_pipeline"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


class VerticalLayout(StrEnum):
    """Como o vídeo original é encaixado no canvas 9:16."""

    # Amplia até preencher e corta o excedente. Perde as laterais de um 16:9.
    CENTER_CROP = "center_crop"
    # Foreground em 4:3 centralizado sobre o próprio vídeo desfocado.
    BLURRED_4_3 = "blurred_4_3"
    # Frame inteiro preservado, sem corte lateral, sobre o vídeo desfocado.
    BLURRED_16_9 = "blurred_16_9"


#: Enquadramento padrão quando o usuário não escolhe nada.
DEFAULT_VIDEO_LAYOUT = VerticalLayout.BLURRED_4_3


class SubtitlePosition(StrEnum):
    """Faixa vertical onde a legenda é ancorada."""

    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class SubtitleStylePreset(StrEnum):
    BOLD = "bold"
    MINIMAL = "minimal"
    OUTLINE = "outline"


class RenderQuality(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    HIGH = "high"


class OutputFps(StrEnum):
    """`ORIGINAL` mantém o FPS da origem; os demais forçam com o filtro `fps`."""

    ORIGINAL = "original"
    FPS_30 = "30"
    FPS_60 = "60"


class SourceType(StrEnum):
    """De onde o vídeo veio."""

    REMOTE = "remote"
    LOCAL = "local"


class FilenamePattern(StrEnum):
    """Como nomear os arquivos exportados."""

    CLIP = "clip"
    TITLE = "title"


class ClipStatus(StrEnum):
    PENDING = "pending"
    RENDERING = "rendering"
    RENDERED = "rendered"
    FAILED = "failed"
