# Automatic YouTube uploads

Clipper imports only the URLs/files you choose. When enabled, completing a render queues every clip for automatic upload. Keep Clipper running until uploads finish. Existing renders are not backfilled automatically.

## Connect once

1. Enable YouTube Data API v3 in Google Cloud, configure OAuth consent and create a Desktop app OAuth client. Add your account as a test user if necessary. Download the client JSON outside Git.
2. Install dependencies: `.venv\Scripts\python -m pip install -e ".[dev]"`.
3. Run `.venv\Scripts\python -m app.cli.youtube connect C:\path\client_secret.json`. Choose SignalCut in your browser and grant access.
4. Add the following to root `.env` and restart Clipper:

```dotenv
YOUTUBE_AUTO_PUBLISH=true
YOUTUBE_CHANNEL_ID=UCIFdqrXY6deb778euhwYKFA
YOUTUBE_PRIVACY=public
```

The uploader checks the channel ID before uploading. Tokens and upload receipts live in ignored storage/. Never share these files. Set the flag false and restart to stop automatic uploads.

## Status and interrupted uploads

`python -m app.cli.youtube status` shows clip state, YouTube ID, and returned privacy. `publish` processes the pending queue manually. Completed entries are skipped on render retry.

Interrupted uploads remain needs_review or uploading. Check YouTube Studio before running `python -m app.cli.youtube retry CLIP_ID --confirmed-not-uploaded`, then `publish`. YouTube does not provide upload idempotency keys, so uncertain uploads are never automatically restarted as new videos.

Google can force uploads from unaudited API projects to private even when public is requested. OAuth consent alone does not remove this restriction. See https://developers.google.com/youtube/v3/docs/videos/insert . Testing-mode OAuth tokens may expire and require reconnecting.

## Windows executable

Run `powershell -File scripts/build-windows.ps1` with Node, Rust and Microsoft C++ build tools installed. It produces Clipper.exe in the project root. Keep backend/ and a Python 3.12 .venv beside it, with the project dependencies installed. FFmpeg/ffprobe must be on PATH. This is a checkout-based executable, not a self-contained installer.
