"""Smoke test do pipeline de ingestão, ponta a ponta, contra a API real.

    SMOKE_VIDEO_URL="https://..." python scripts/smoke_pipeline.py

A URL vem do ambiente de propósito: baixar vídeo de terceiros depende de
direito de uso, então quem roda escolhe. Este script não faz parte da suíte
automatizada — ele usa rede.

Pressupõe API e worker no ar:

    alembic upgrade head
    uvicorn app.main:app --app-dir backend --port 8000
    python -m app.worker
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

API_BASE = os.environ.get("SMOKE_API_BASE", "http://127.0.0.1:8000")
STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "storage"))
TIMEOUT_SECONDS = float(os.environ.get("SMOKE_TIMEOUT", "600"))

TERMINAL_VIDEO_STATUSES = {"downloaded", "failed", "cancelled"}


class SmokeFailure(Exception):
    pass


def _check(condition: bool, message: str) -> None:
    print(f"  {'OK  ' if condition else 'FALHA'} {message}")
    if not condition:
        raise SmokeFailure(message)


def _poll(client: httpx.Client, video_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_progress = -1

    while time.monotonic() < deadline:
        video: dict[str, Any] = client.get(f"/api/v1/videos/{video_id}").json()
        if video["progress"] != last_progress:
            last_progress = video["progress"]
            print(f"  ... {video['status']} {video['progress']}% ({video['current_stage']})")
        if video["status"] in TERMINAL_VIDEO_STATUSES:
            return video
        time.sleep(2)

    raise SmokeFailure("Tempo esgotado esperando o worker.")


def main() -> int:
    url = os.environ.get("SMOKE_VIDEO_URL")
    if not url:
        print("Defina SMOKE_VIDEO_URL com uma URL que você tenha direito de baixar.")
        return 2

    with httpx.Client(base_url=API_BASE, timeout=30) as client:
        print("1. POST /api/v1/videos")
        started = time.perf_counter()
        response = client.post("/api/v1/videos", json={"url": url})
        elapsed = time.perf_counter() - started

        _check(response.status_code == 202, f"HTTP 202 (recebido {response.status_code})")
        _check(elapsed < 2.0, f"resposta imediata ({elapsed:.2f}s, sem esperar download)")

        created = response.json()
        video_id = created["id"]
        _check(created["status"] == "queued", "Video criado como queued")
        _check(created["progress"] == 0, "progress inicial 0")

        print("2. jobs do vídeo")
        jobs = client.get(f"/api/v1/videos/{video_id}/jobs").json()
        _check(len(jobs) == 1 and jobs[0]["job_type"] == "ingest", "Job ingest queued criado")

        print("3. aguardando o worker")
        video = _poll(client, video_id)

        print("4. resultado")
        if video["status"] == "failed":
            raise SmokeFailure(f"Ingestão falhou: {video['error_code']} — {video['error_message']}")

        _check(video["status"] == "downloaded", "Video downloaded")
        _check(video["progress"] == 100, "progress 100")
        _check(video["error_code"] is None, "sem erro registrado")
        _check(video["duration"] is not None, "duração preenchida pelo ffprobe")
        _check(video["width"] is not None and video["height"] is not None, "resolução preenchida")

        job = client.get(f"/api/v1/videos/{video_id}/jobs").json()[0]
        _check(job["status"] == "succeeded", "Job succeeded")
        _check(job["attempt"] == 1, f"uma única tentativa (attempt={job['attempt']})")
        _check(job["finished_at"] is not None, "finished_at preenchido")

        print("5. storage e vazamento de path")
        payload = client.get(f"/api/v1/videos/{video_id}").text
        _check("source_file_key" not in payload, "API não expõe source_file_key")
        _check(str(STORAGE_ROOT.resolve()) not in payload, "API não expõe path absoluto")

        downloads = STORAGE_ROOT / "downloads"
        candidates = list(downloads.glob("*/source.*"))
        _check(bool(candidates), f"arquivo presente em {downloads}/<id>/source.*")

        for timestamp in (video["created_at"], job["created_at"]):
            _check(timestamp.endswith("Z"), f"timestamp em UTC explícito ({timestamp})")

    print("\nPipeline saudável.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"\nSMOKE TEST FALHOU: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
