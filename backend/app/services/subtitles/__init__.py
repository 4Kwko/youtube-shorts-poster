"""Preparação de legendas por clip."""

from __future__ import annotations

from app.services.subtitles.ass import (
    BOLD_STYLE,
    SubtitleStyle,
    build_ass,
    escape_ass_text,
    format_timestamp,
    get_style,
    wrap_text,
)
from app.services.subtitles.chunking import SubtitleEvent, build_events
from app.services.subtitles.errors import SubtitleError, SubtitleGenerationError
from app.services.subtitles.mapping import slice_transcript
from app.services.subtitles.storage import (
    SUBTITLES_SUBDIR,
    delete_subtitles,
    subtitle_file_key,
    subtitle_path,
    write_subtitle,
)

__all__ = [
    "BOLD_STYLE",
    "SUBTITLES_SUBDIR",
    "SubtitleError",
    "SubtitleEvent",
    "SubtitleGenerationError",
    "SubtitleStyle",
    "build_ass",
    "build_events",
    "delete_subtitles",
    "escape_ass_text",
    "format_timestamp",
    "get_style",
    "slice_transcript",
    "subtitle_file_key",
    "subtitle_path",
    "wrap_text",
    "write_subtitle",
]
