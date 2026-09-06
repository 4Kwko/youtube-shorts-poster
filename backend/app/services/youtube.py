"""Durable upload queue for selected rendered clips."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import Settings

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def token_path(settings: Settings) -> Path:
    return settings.storage_root / "youtube-token.json"


def client(settings: Settings) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    path = token_path(settings)
    if not path.is_file():
        raise RuntimeError("Connect YouTube first using app.cli.youtube connect.")
    credentials = Credentials.from_authorized_user_file(str(path), SCOPES)  # type: ignore[no-untyped-call]
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        path.write_text(credentials.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


@contextmanager
def ledger(settings: Settings) -> Iterator[sqlite3.Connection]:
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.storage_root / "youtube-uploads.db", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS uploads (
        clip_id TEXT PRIMARY KEY, path TEXT NOT NULL, title TEXT NOT NULL,
        description TEXT NOT NULL, privacy TEXT NOT NULL, state TEXT NOT NULL,
        youtube_id TEXT, actual_privacy TEXT, error TEXT)""")
    try:
        with db:
            yield db
    finally:
        db.close()


def enqueue(settings: Settings, clip_id: str, path: Path, title: str, source: str) -> None:
    with ledger(settings) as db:
        db.execute(
            "INSERT OR IGNORE INTO uploads VALUES (?, ?, ?, ?, ?, 'queued', NULL, NULL, NULL)",
            (
                clip_id,
                str(path.resolve()),
                title.replace("<", "").replace(">", "")[:100],
                f"Source: {source}" if source else "",
                settings.youtube_privacy,
            ),
        )


def drain(settings: Settings, service: Any = None) -> None:
    """Atomic claims prevent duplicate inserts across workers and render retries.

    Interrupted uploads require reconciliation: YouTube has no idempotency key.
    Never automatically create another insert after an uncertain outcome.
    """
    from googleapiclient.http import MediaFileUpload  # type: ignore[import-untyped]

    with ledger(settings) as db:
        rows = db.execute("SELECT * FROM uploads WHERE state='queued' ORDER BY rowid").fetchall()
    if not rows:
        return
    service = service or client(settings)
    channels = service.channels().list(part="id", mine=True).execute()
    if settings.youtube_channel_id not in [item["id"] for item in channels.get("items", [])]:
        raise RuntimeError("Connected channel differs from YOUTUBE_CHANNEL_ID; upload stopped.")
    for row in rows:
        path = Path(row["path"]).resolve()
        if (
            not path.is_relative_to((settings.storage_root / "renders").resolve())
            or not path.is_file()
        ):
            with ledger(settings) as db:
                db.execute(
                    "UPDATE uploads SET state='needs_review', error=? "
                    "WHERE clip_id=? AND state='queued'",
                    ("Rendered file missing or outside storage/renders.", row["clip_id"]),
                )
            continue
        with ledger(settings) as db:
            claimed = db.execute(
                "UPDATE uploads SET state='uploading' WHERE clip_id=? AND state='queued'",
                (row["clip_id"],),
            ).rowcount
        if not claimed:
            continue
        try:
            request = service.videos().insert(
                part="snippet,status",
                notifySubscribers=False,
                body={
                    "snippet": {"title": row["title"], "description": row["description"]},
                    "status": {"privacyStatus": row["privacy"]},
                },
                media_body=MediaFileUpload(
                    str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True
                ),
            )
            response = None
            while response is None:
                _, response = request.next_chunk(num_retries=3)
            video_id = response["id"]
            actual = response.get("status", {}).get("privacyStatus", "unknown")
            with ledger(settings) as db:
                db.execute(
                    "UPDATE uploads SET state='uploaded', youtube_id=?, actual_privacy=? "
                    "WHERE clip_id=?",
                    (video_id, actual, row["clip_id"]),
                )
        except Exception:
            with ledger(settings) as db:
                db.execute(
                    "UPDATE uploads SET state='needs_review', error=? WHERE clip_id=?",
                    ("Upload interrupted. Check YouTube Studio before retrying.", row["clip_id"]),
                )
            raise


def report(settings: Settings) -> str:
    with ledger(settings) as db:
        rows = db.execute(
            "SELECT clip_id,title,state,youtube_id,actual_privacy,error FROM uploads"
        ).fetchall()
    return json.dumps([dict(row) for row in rows], indent=2, ensure_ascii=False)
