from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import NotFoundError


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/rota-inexistente")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]


def test_app_error_maps_to_status_and_code(app: FastAPI) -> None:
    async def boom() -> None:
        raise NotFoundError("Vídeo não encontrado.", details={"video_id": "abc"})

    app.add_api_route("/_test/app-error", boom, methods=["GET"])

    with TestClient(app) as client:
        response = client.get("/_test/app-error")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "Vídeo não encontrado."
    assert body["error"]["details"] == {"video_id": "abc"}


def test_unhandled_exception_does_not_leak_internals(app: FastAPI) -> None:
    async def boom() -> None:
        raise RuntimeError("/srv/interno/segredo.mp4 quebrou")

    app.add_api_route("/_test/crash", boom, methods=["GET"])

    # raise_server_exceptions=False faz o TestClient exercitar o handler global
    # em vez de propagar a exceção para o teste.
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/crash")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "segredo" not in response.text
    assert "/srv/" not in response.text
    assert body["request_id"]


@pytest.mark.parametrize("value", ["abc", "-1"])
def test_validation_error_envelope(app: FastAPI, value: str) -> None:
    async def echo(quantidade: int) -> dict[str, int]:
        return {"quantidade": quantidade}

    app.add_api_route("/_test/echo", echo, methods=["GET"])

    with TestClient(app) as client:
        response = client.get("/_test/echo", params={"quantidade": value})

    if value == "abc":
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["details"]["fields"]
    else:
        assert response.status_code == 200
