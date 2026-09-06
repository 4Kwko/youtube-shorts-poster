from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.schemas.media import MediaInfo
from app.services.youtube import drain, enqueue, ledger


@pytest.fixture(autouse=True)
def mock_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.youtube.probe_file",
        lambda *args, **kwargs: MediaInfo(width=1080, height=1920, duration_seconds=30),
    )


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


@pytest.mark.parametrize(
    "width,height,duration", [(1920, 1080, 30), (1080, 1920, 181), (1080, 1920, None)]
)
def test_non_shorts_never_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int, height: int, duration: float | None
) -> None:
    monkeypatch.setattr(
        "app.services.youtube.probe_file",
        lambda *args, **kwargs: MediaInfo(width=width, height=height, duration_seconds=duration),
    )
    settings, service = setup_queue(tmp_path)
    drain(settings, service)
    service.videos.assert_not_called()
    with ledger(settings) as db:
        assert db.execute("SELECT state FROM uploads").fetchone()[0] == "needs_review"


def test_preferences_are_snapshotted_and_pause_stops_upload(tmp_path: Path) -> None:
    from app.services.youtube_preferences import PublishingPreferences, save_preferences

    settings, service = setup_queue(tmp_path)
    save_preferences(
        settings,
        PublishingPreferences(
            enabled=True, description="Minha legenda", hashtags="Shorts #Teste #Teste"
        ),
    )
    enqueue(settings, "second", tmp_path / "renders/clip.mp4", "Segundo", "")
    save_preferences(settings, PublishingPreferences(enabled=False, description="Outra"))
    drain(settings, service, respect_pause=True)
    service.videos.assert_not_called()
    with ledger(settings) as db:
        assert db.execute("SELECT description FROM uploads WHERE clip_id='second'").fetchone()[
            0
        ] == ("Minha legenda\n\n#Shorts #Teste")
