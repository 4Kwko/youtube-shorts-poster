"""Read-only upload queue status; credentials never leave the backend."""

import json
from typing import Any

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.services.youtube import report, token_path

router = APIRouter(prefix="/youtube", tags=["youtube"])


@router.get("/status")
def status(settings: SettingsDep) -> dict[str, Any]:
    return {
        "enabled": settings.youtube_auto_publish,
        "connected": token_path(settings).is_file(),
        "uploads": json.loads(report(settings)),
    }
