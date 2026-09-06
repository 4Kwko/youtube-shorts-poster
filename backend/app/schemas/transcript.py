"""Contratos da transcrição.

O mesmo modelo serve para o JSON persistido e para a resposta da API. `version`
existe para que um formato futuro possa ser distinguido sem adivinhação.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

TRANSCRIPT_FORMAT_VERSION = 1


class TranscriptWord(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    word: str


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)


class TranscriptResult(BaseModel):
    """Transcrição completa, com timestamps relativos ao vídeo original."""

    version: int = TRANSCRIPT_FORMAT_VERSION
    language: str | None = None
    language_probability: float | None = Field(default=None, ge=0, le=1)
    duration: float | None = Field(default=None, ge=0)
    segments: list[TranscriptSegment] = Field(default_factory=list)


class TranscriptResponse(BaseModel):
    """Resposta da API. `file_key` não faz parte do contrato público."""

    video_id: str
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None
    segments: list[TranscriptSegment]
