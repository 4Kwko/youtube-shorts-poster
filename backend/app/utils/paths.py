"""Resolução de caminhos dentro do storage.

Regra do projeto: a API nunca recebe caminho de arquivo. Ela recebe um nome
dentro de um subdiretório conhecido de storage, e este módulo é o único lugar
que transforma isso em caminho absoluto — depois de provar que o resultado não
escapou da raiz permitida.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

from app.core.config import Settings

# Nome de arquivo aceito: sem separador de diretório, sem componentes especiais
# e sem caracteres de controle. Extensão e sufixos são livres.
_FORBIDDEN_SUBSTRINGS = ("/", "\\", "\x00")


def validate_filename(filename: str) -> str:
    """Valida um nome de arquivo vindo de fora. Retorna o nome normalizado."""
    name = unicodedata.normalize("NFC", filename).strip()

    if not name or name in {".", ".."}:
        raise ValueError("Nome de arquivo vazio ou inválido.")
    if any(token in name for token in _FORBIDDEN_SUBSTRINGS):
        raise ValueError("Nome de arquivo não pode conter separadores de diretório.")
    if any(ord(char) < 32 for char in name):
        raise ValueError("Nome de arquivo contém caracteres de controle.")
    if len(name.encode("utf-8")) > 255:
        raise ValueError("Nome de arquivo excede o limite de 255 bytes.")

    return name


def resolve_storage_path(settings: Settings, subdir: str, *parts: str) -> Path:
    """Caminho absoluto dentro de um subdiretório de storage.

    Cada componente é validado isoladamente como nome de arquivo, então nenhum
    deles pode conter separador ou `..`. Levanta `ValueError` se o subdiretório
    for desconhecido, se algum componente for inválido ou se o caminho
    resolvido cair fora da raiz — o `resolve()` também cobre symlink apontando
    para fora do storage.
    """
    if not parts:
        raise ValueError("Nenhum componente de caminho informado.")

    base = settings.storage_path(subdir).resolve()
    candidate = base
    for part in parts:
        candidate = candidate / validate_filename(part)
    candidate = candidate.resolve()

    if base not in candidate.parents:
        raise ValueError("Caminho resolvido fora do diretório de storage.")

    return candidate


def resolve_storage_file(settings: Settings, subdir: str, filename: str) -> Path:
    """Caminho absoluto de um arquivo na raiz de um subdiretório de storage."""
    return resolve_storage_path(settings, subdir, filename)


def is_inside(base: Path, candidate: Path) -> bool:
    """Confirma que `candidate` está sob `base`, resolvendo symlinks."""
    try:
        resolved_base = base.resolve()
        resolved_candidate = candidate.resolve()
    except OSError:
        return False
    return resolved_base in resolved_candidate.parents
