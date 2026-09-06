"""Contratos HTTP de Clip.

`source_file_key` e `rendered_file_key` ficam de fora: são referências de
storage e não fazem parte do contrato público.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import ClipStatus
from app.schemas.common import UTCDatetime


class ClipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    sequence: int
    start_time: float
    end_time: float
    duration: float
    status: ClipStatus
    created_at: UTCDatetime
    updated_at: UTCDatetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def media_url(self) -> str | None:
        """Rota de reprodução. `None` enquanto não houver render."""
        return f"/api/v1/clips/{self.id}/media" if self.status is ClipStatus.RENDERED else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def download_url(self) -> str | None:
        return f"/api/v1/clips/{self.id}/download" if self.status is ClipStatus.RENDERED else None
