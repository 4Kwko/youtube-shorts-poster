import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services.youtube_auth import LoginSession, save_oauth_config


def test_preferences_persist_without_restart(client: TestClient) -> None:
    payload = {
        "enabled": True,
        "description": "Sempre igual",
        "hashtags": "#Shorts",
        "privacy": "private",
    }
    assert client.put("/api/v1/youtube/preferences", json=payload).status_code == 200
    assert client.get("/api/v1/youtube/status").json()["preferences"] == payload


def test_shorts_duration_and_old_preferences() -> None:
    from app.schemas.settings import VideoSettings

    with pytest.raises(ValueError):
        VideoSettings(clip_duration_seconds=300)
    restored = VideoSettings.from_stored({"clip_duration_seconds": 300, "volume": 42})
    assert restored.clip_duration_seconds == 180
    assert restored.volume == 42


def test_foreign_origin_cannot_change_preferences(client: TestClient) -> None:
    result = client.put(
        "/api/v1/youtube/preferences",
        json={"enabled": True},
        headers={"Origin": "https://example.com"},
    )
    assert result.status_code == 403


def test_invalid_client_has_no_secrets_in_response(client: TestClient) -> None:
    result = client.put("/api/v1/youtube/client", json={"content": "secret-marker"})
    assert result.status_code == 422
    assert "secret-marker" not in result.text


def test_connect_reports_missing_configuration(client: TestClient) -> None:
    assert client.post("/api/v1/youtube/connect").status_code == 422


@pytest.mark.parametrize(
    "channel_id,expected", [("wrong", "error"), ("UCIFdqrXY6deb778euhwYKFA", "connected")]
)
def test_login_validates_channel_before_saving(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, channel_id: str, expected: str
) -> None:
    from app.services.youtube import token_path

    credentials = MagicMock()
    credentials.to_json.return_value = '{"saved":true}'
    flow = MagicMock()
    flow.run_local_server.return_value = credentials
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", lambda *args: flow
    )
    service = MagicMock()
    service.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"id": channel_id, "snippet": {"title": "SignalCut"}}]
    }
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *args, **kwargs: service)
    login = LoginSession()
    login._connect(settings, {})
    assert login.state == expected
    assert token_path(settings).exists() == (expected == "connected")


def test_reject_non_google_oauth_endpoint(settings: Settings) -> None:
    with pytest.raises(ValueError):
        save_oauth_config(
            settings,
            json.dumps(
                {
                    "installed": {
                        "client_id": "id",
                        "client_secret": "secret",
                        "auth_uri": "https://evil.example",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
            ),
        )


def test_status_never_returns_token(client: TestClient, app: FastAPI, settings: Settings) -> None:
    from app.services.youtube import token_path

    token_path(settings).write_text('{"client_id":"id","client_secret":"secret-marker"}')
    app.state.youtube_login.channel = "SignalCut"
    response = client.get("/api/v1/youtube/status")
    assert response.json()["connected"]
    assert response.json()["configured"]
    assert "secret-marker" not in response.text
