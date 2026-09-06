"""Nome dos arquivos exportados.

Toda a lógica de filename mora aqui: sanitização, padrão e resolução de
colisão. Nada disso pode depender de texto vindo do provedor sem passar por
esta camada.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from app.models.enums import FilenamePattern

# Proibidos no Windows, mais os separadores e caracteres de controle.
_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# Nomes reservados do Windows: um arquivo `CON.mp4` é inutilizável.
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MAX_TITLE_LENGTH = 60
FALLBACK_STEM = "clip"


def sanitize_title(title: str | None) -> str:
    """Transforma o título do provedor num nome de arquivo seguro.

    Vazio depois da limpeza vira o fallback: um nome sem parte de título é
    melhor do que um arquivo chamado `.mp4`.
    """
    if not title:
        return FALLBACK_STEM

    normalized = unicodedata.normalize("NFC", title)
    cleaned = _INVALID.sub(" ", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # O Windows recusa nome terminado em espaço ou ponto.
    cleaned = cleaned.rstrip(" .")[:MAX_TITLE_LENGTH].rstrip(" .")

    if not cleaned or cleaned.upper() in _RESERVED:
        return FALLBACK_STEM
    return cleaned


def build_filename(pattern: FilenamePattern, sequence: int, title: str | None = None) -> str:
    """`clip-001.mp4` ou `titulo-001.mp4`, conforme o padrão escolhido."""
    number = f"{sequence + 1:03d}"
    if pattern is FilenamePattern.TITLE:
        return f"{sanitize_title(title)}-{number}.mp4"
    return f"clip-{number}.mp4"


def resolve_collision(directory: Path, filename: str) -> Path:
    """Caminho livre dentro do diretório, sem sobrescrever nada.

    `clip-001.mp4` ocupado vira `clip-001 (2).mp4`.
    """
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem, suffix = candidate.stem, candidate.suffix
    for attempt in range(2, 1000):
        alternative = directory / f"{stem} ({attempt}){suffix}"
        if not alternative.exists():
            return alternative

    raise ValueError("Não foi possível encontrar um nome livre para o arquivo.")
