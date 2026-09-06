from __future__ import annotations

import shutil
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services.media import binaries as binaries_module
from app.services.media.binaries import clear_binary_cache
from app.services.media.runner import CommandResult


def test_health_returns_ok(client: TestClient, settings: Settings) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["name"] == settings.app_name
    assert body["version"] == settings.app_version
    assert body["environment"] == "test"
    assert body["uptime_seconds"] >= 0


def test_health_sets_request_id_header(client: TestClient) -> None:
    response = client.get("/health")

    assert uuid.UUID(response.headers["X-Request-ID"])


def test_health_echoes_valid_client_request_id(client: TestClient) -> None:
    provided = str(uuid.uuid4())

    response = client.get("/health", headers={"X-Request-ID": provided})

    assert response.headers["X-Request-ID"] == provided


def test_health_replaces_malformed_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "not-a-uuid; drop table"})

    assert response.headers["X-Request-ID"] != "not-a-uuid; drop table"
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_storage_dirs_created_on_startup(client: TestClient, settings: Settings) -> None:
    client.get("/health")

    for subdir in ("downloads", "audio", "clips", "renders", "tmp"):
        assert (settings.storage_root / subdir).is_dir()


def test_health_reports_dependencies(client: TestClient) -> None:
    body = client.get("/health").json()

    assert set(body["dependencies"]) == {"ffmpeg", "ffprobe"}
    assert isinstance(body["dependencies"]["ffmpeg"], bool)
    assert isinstance(body["dependencies"]["ffprobe"], bool)


def test_health_ok_when_dependencies_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_binary_cache()
    monkeypatch.setattr(shutil, "which", lambda _: None)

    response = client.get("/health")
    clear_binary_cache()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"] == {"ffmpeg": False, "ffprobe": False}


def test_health_never_exposes_binary_paths_or_versions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_binary_cache()
    monkeypatch.setattr(shutil, "which", lambda name: f"/opt/secreto/{name}")
    monkeypatch.setattr(
        binaries_module,
        "run_command",
        lambda args, timeout: CommandResult(0, "ffmpeg version 6.1.1 Copyright", ""),
    )

    response = client.get("/health")
    clear_binary_cache()

    assert response.json()["dependencies"]["ffmpeg"] is True
    assert "/opt/secreto" not in response.text
    assert "6.1.1" not in response.text
