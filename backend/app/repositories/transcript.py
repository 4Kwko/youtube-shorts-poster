"""Acesso a dados de Transcript. Sem regra de negócio e sem commit."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transcript import Transcript


class TranscriptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_video(self, video_id: str) -> Transcript | None:
        stmt = select(Transcript).where(Transcript.video_id == video_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def upsert(
        self,
        *,
        video_id: str,
        file_key: str,
        language: str | None = None,
        language_probability: float | None = None,
    ) -> Transcript:
        """Cria ou atualiza a transcrição do vídeo.

        `video_id` é unique: um retry atualiza a linha existente em vez de
        violar a constraint.
        """
        transcript = self.get_for_video(video_id)

        if transcript is None:
            transcript = Transcript(video_id=video_id, file_key=file_key)
            self._session.add(transcript)

        transcript.file_key = file_key
        transcript.language = language
        transcript.language_probability = language_probability
        self._session.flush()
        return transcript
