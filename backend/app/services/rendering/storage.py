"""Localização dos renders finais no storage."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.utils.paths import resolve_storage_path

RENDERS_SUBDIR = "renders"


def render_path(settings: Settings, rendered_file_key: str) -> Path:
    """Caminho absoluto de um render a partir da chave gravada no banco.

    A chave vem sempre do banco, nunca do cliente, e ainda assim passa pela
    validação de componentes de `resolve_storage_path`.
    """
    return resolve_storage_path(settings, RENDERS_SUBDIR, *rendered_file_key.split("/"))
