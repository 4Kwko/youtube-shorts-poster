from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.services.youtube import drain, enqueue, ledger


def setup_queue(tmp_path: Path) -> tuple[Settings, MagicMock]:
    settings = Settings(_env_file=None, storage_root=tmp_path)
    path = tmp_path / "renders" / "clip.mp4"
    path.parent.mkdir()
    path.write_bytes(b"test")
    enqueue(settings, "clip", path, "A title", "https://youtube.com/watch?v=test")
    service = MagicMock()
    service.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"id": settings.youtube_channel_id}]
    }
    service.videos.return_value.insert.return_value.next_chunk.return_value = (
        None,
        {"id": "uploaded", "status": {"privacyStatus": "private"}},
    )
    return settings, service


def test_success_is_not_uploaded_again(tmp_path: Path) -> None:
    settings, service = setup_queue(tmp_path)
    drain(settings, service)
    enqueue(settings, "clip", tmp_path / "renders/clip.mp4", "Changed title", "")
    drain(settings, service)
    service.videos.return_value.insert.assert_called_once()
    with ledger(settings) as db:
        row = db.execute("SELECT * FROM uploads").fetchone()
    assert row["youtube_id"] == "uploaded"
    assert row["actual_privacy"] == "private"


def test_uncertain_upload_is_held(tmp_path: Path) -> None:
    settings, service = setup_queue(tmp_path)
    service.videos.return_value.insert.return_value.next_chunk.side_effect = OSError(
        "lost response"
    )
    with pytest.raises(OSError):
        drain(settings, service)
    drain(settings, service)
    service.videos.return_value.insert.assert_called_once()
    with ledger(settings) as db:
        assert db.execute("SELECT state FROM uploads").fetchone()[0] == "needs_review"


def test_wrong_channel_never_uploads(tmp_path: Path) -> None:
    settings, service = setup_queue(tmp_path)
    service.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "other"}]
    }
    with pytest.raises(RuntimeError, match="channel"):
        drain(settings, service)
    service.videos.assert_not_called()


def test_missing_render_is_held(tmp_path: Path) -> None:
    settings, service = setup_queue(tmp_path)
    (tmp_path / "renders/clip.mp4").unlink()
    drain(settings, service)
    service.videos.assert_not_called()
    with ledger(settings) as db:
        assert db.execute("SELECT state FROM uploads").fetchone()[0] == "needs_review"
