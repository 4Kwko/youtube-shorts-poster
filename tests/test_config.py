from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test ,")

    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_storage_root_is_absolute() -> None:
    settings = Settings(_env_file=None, storage_root=Path("storage"))

    assert settings.storage_root.is_absolute()


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ValueError, match="LOG_LEVEL inválido"):
        Settings(_env_file=None, log_level="TRACE")


def test_storage_path_rejects_unknown_subdir(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, storage_root=tmp_path)

    with pytest.raises(ValueError, match="desconhecido"):
        settings.storage_path("../etc")
