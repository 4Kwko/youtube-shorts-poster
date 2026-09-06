"""Local channel connection, publishing preferences and queue status."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import SettingsDep
from app.services.youtube import publishing_error, report, token_path
from app.services.youtube_auth import LoginSession, oauth_config, save_oauth_config
from app.services.youtube_preferences import PublishingPreferences, preferences, save_preferences


def local_origin(request: Request, settings: SettingsDep) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        raise HTTPException(403, "Origem não permitida.")


router = APIRouter(prefix="/youtube", tags=["youtube"], dependencies=[Depends(local_origin)])


@router.get("/status")
def status(request: Request, settings: SettingsDep) -> dict[str, Any]:
    login: LoginSession = request.app.state.youtube_login
    try:
        oauth_config(settings)
        configured = True
    except (ValueError, KeyError):
        configured = False
    return {
        "enabled": preferences(settings).enabled,
        "connected": token_path(settings).is_file(),
        "configured": configured,
        "channel": login.channel,
        "channel_id": settings.youtube_channel_id,
        "login_state": login.state,
        "login_error": login.error,
        "publishing_error": publishing_error(settings),
        "preferences": preferences(settings).model_dump(),
        "uploads": json.loads(report(settings)),
    }


class ClientConfig(BaseModel):
    content: str = Field(max_length=20000)


@router.put("/client")
def configure(payload: ClientConfig, settings: SettingsDep) -> dict[str, bool]:
    try:
        save_oauth_config(settings, payload.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"saved": True}


@router.post("/connect")
def connect(request: Request, settings: SettingsDep) -> dict[str, bool]:
    try:
        request.app.state.youtube_login.start(settings)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, "Importe o JSON do cliente Google Desktop primeiro.") from exc
    return {"started": True}


@router.put("/preferences")
def update_preferences(
    payload: PublishingPreferences, settings: SettingsDep
) -> PublishingPreferences:
    save_preferences(settings, payload)
    return payload
