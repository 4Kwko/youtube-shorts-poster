"""Contratos HTTP de Job."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.enums import JobStatus, JobType
from app.schemas.common import UTCDatetime


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: JobType
    status: JobStatus
    attempt: int
    max_attempts: int
    progress: int
    current_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: UTCDatetime
    started_at: UTCDatetime | None = None
    finished_at: UTCDatetime | None = None
