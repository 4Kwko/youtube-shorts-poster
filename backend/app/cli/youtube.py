"""Connect a YouTube channel and inspect or resume the upload queue."""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.services.youtube import SCOPES, drain, ledger, report, token_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    connect = commands.add_parser("connect")
    connect.add_argument("client_json")
    commands.add_parser("status")
    commands.add_parser("publish")
    retry = commands.add_parser("retry", help="Only after checking Studio for duplicates")
    retry.add_argument("clip_id")
    retry.add_argument("--confirmed-not-uploaded", action="store_true", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "connect":
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

        flow = InstalledAppFlow.from_client_secrets_file(args.client_json, SCOPES)
        credentials = flow.run_local_server(host="127.0.0.1", port=0, timeout_seconds=300)
        from googleapiclient.discovery import build  # type: ignore[import-untyped]

        service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        channels = service.channels().list(part="id,snippet", mine=True).execute()
        if settings.youtube_channel_id not in [item["id"] for item in channels.get("items", [])]:
            raise RuntimeError("Choose the channel matching YOUTUBE_CHANNEL_ID. Nothing saved.")
        path = token_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(credentials.to_json(), encoding="utf-8")
        for channel in channels.get("items", []):
            print(channel["id"], channel["snippet"]["title"])
        from pathlib import Path

        from dotenv import set_key

        from app.services.youtube_auth import save_oauth_config
        from app.services.youtube_preferences import preferences, save_preferences

        save_oauth_config(settings, Path(args.client_json).read_text(encoding="utf-8"))
        options = preferences(settings)
        options.enabled = True
        save_preferences(settings, options)
        set_key(".env", "YOUTUBE_AUTO_PUBLISH", "true")
        print("Automatic publishing enabled. Restart Clipper to start uploads.")
    elif args.command == "retry":
        with ledger(settings) as db:
            db.execute(
                "UPDATE uploads SET state='queued', error=NULL "
                "WHERE clip_id=? AND state IN ('needs_review','uploading')",
                (args.clip_id,),
            )
    elif args.command == "publish":
        drain(settings)
    print(report(settings))


if __name__ == "__main__":
    main()
