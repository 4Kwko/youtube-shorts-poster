"""Desktop OAuth login. Credentials remain in local ignored storage."""

from __future__ import annotations

import json
import threading
from typing import Any

from app.core.config import Settings
from app.services.youtube import SCOPES, token_path


def oauth_config(settings: Settings) -> dict[str, Any]:
    path = settings.storage_root / "youtube" / "client.json"
    if path.is_file():
        return dict(json.loads(path.read_text(encoding="utf-8")))
    if token_path(settings).is_file():
        token = json.loads(token_path(settings).read_text(encoding="utf-8"))
        return {
            "installed": {
                "client_id": token["client_id"],
                "client_secret": token["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    raise ValueError("Selecione primeiro o JSON do cliente Google Desktop.")


def save_oauth_config(settings: Settings, text: str) -> None:
    try:
        installed = json.loads(text)["installed"]
        if not installed["client_id"] or not installed["client_secret"]:
            raise ValueError
        if installed["auth_uri"] != "https://accounts.google.com/o/oauth2/auth":
            raise ValueError
        if installed["token_uri"] != "https://oauth2.googleapis.com/token":  # noqa: S105
            raise ValueError
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Use o JSON de um cliente OAuth Google do tipo Desktop app.") from exc
    path = settings.storage_root / "youtube" / "client.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"installed": installed}), encoding="utf-8")


class LoginSession:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "idle"
        self.error: str | None = None
        self.channel: str | None = None

    def start(self, settings: Settings) -> None:
        with self.lock:
            if self.state == "connecting":
                return
            config = oauth_config(settings)
            self.state, self.error = "connecting", None
            threading.Thread(target=self._connect, args=(settings, config), daemon=True).start()

    def _connect(self, settings: Settings, config: dict[str, Any]) -> None:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            flow = InstalledAppFlow.from_client_config(config, SCOPES)
            credentials = flow.run_local_server(
                host="127.0.0.1",
                port=0,
                timeout_seconds=300,
                prompt="consent",
                authorization_prompt_message="",
                success_message="Canal conectado. Pode voltar ao Clipper.",
            )
            service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
            items = service.channels().list(part="id,snippet", mine=True).execute().get("items", [])
            channel = next((c for c in items if c["id"] == settings.youtube_channel_id), None)
            if channel is None:
                self.error = (
                    "Escolha a conta do canal configurado no Clipper. Conexão não alterada."
                )
                self.state = "error"
                return
            path = token_path(settings)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(credentials.to_json(), encoding="utf-8")
            temporary.replace(path)
            self.channel = channel["snippet"]["title"]
            self.state = "connected"
        except Exception:
            self.error = "Login não concluído. Confira o usuário de teste e tente novamente."
            self.state = "error"
