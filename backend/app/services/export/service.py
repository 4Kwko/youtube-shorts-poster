"""Cópia dos renders finais para a pasta escolhida pelo usuário.

Exceção deliberada à regra de storage interno: este é o único módulo que
escreve fora de `storage/`. O diretório vem das settings do vídeo (escolhido
pelo diálogo nativo do app) e passa por `validate_output_directory` antes de
qualquer escrita. Nada aqui usa os helpers de storage interno.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.models.enums import FilenamePattern
from app.services.export.errors import ExportFailedError, InvalidOutputDirectoryError
from app.services.export.naming import build_filename, resolve_collision

logger = logging.getLogger(__name__)

# Cópia em blocos: um clip de 90s em 1080x1920 não cabe confortavelmente em RAM.
COPY_BUFFER_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExportedClip:
    sequence: int
    filename: str
    size_bytes: int


def validate_output_directory(raw_path: str) -> Path:
    """Valida (e cria, se preciso) o diretório de saída.

    Exige caminho absoluto: o app envia o que o diálogo nativo devolveu, e um
    caminho relativo aqui significaria escrever em algum lugar dependente do
    diretório de trabalho do worker.
    """
    if not raw_path or not raw_path.strip():
        raise InvalidOutputDirectoryError("Nenhuma pasta de saída definida.")

    path = Path(raw_path.strip())
    if not path.is_absolute():
        raise InvalidOutputDirectoryError("A pasta de saída deve ser um caminho absoluto.")
    if ".." in path.parts:
        raise InvalidOutputDirectoryError("A pasta de saída não pode conter '..'.")

    resolved = path.resolve()

    if resolved.exists():
        if not resolved.is_dir():
            raise InvalidOutputDirectoryError("O caminho informado não é uma pasta.")
    else:
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Não foi possível criar a pasta de saída")
            raise InvalidOutputDirectoryError("Não foi possível criar a pasta de saída.") from exc

    probe = resolved / ".clipper-write-test"
    try:
        probe.touch()
        probe.unlink()
    except OSError as exc:
        raise InvalidOutputDirectoryError("Sem permissão de escrita na pasta de saída.") from exc

    return resolved


def _already_exported(destination: Path, source: Path) -> bool:
    """Arquivo do mesmo tamanho no destino: retry não copia de novo."""
    return destination.is_file() and destination.stat().st_size == source.stat().st_size


def export_clips(
    sources: list[tuple[int, Path]],
    destination: Path,
    *,
    pattern: FilenamePattern,
    title: str | None = None,
) -> list[ExportedClip]:
    """Copia os renders para a pasta de saída.

    Falha em qualquer arquivo aborta a exportação inteira — os renders internos
    continuam onde estavam, e o retry recomeça daqui.
    """
    exported: list[ExportedClip] = []

    for sequence, source in sources:
        if not source.is_file():
            raise ExportFailedError("Um dos clips renderizados não está mais disponível.")

        filename = build_filename(pattern, sequence, title)
        target = destination / filename

        if _already_exported(target, source):
            logger.info("Clip já exportado; cópia ignorada", extra={"sequence": sequence})
            exported.append(ExportedClip(sequence, target.name, target.stat().st_size))
            continue

        target = resolve_collision(destination, filename)
        partial = target.with_name(f"{target.name}.part")

        try:
            with source.open("rb") as origin, partial.open("wb") as copy:
                shutil.copyfileobj(origin, copy, COPY_BUFFER_BYTES)
            # Rename só no fim: nenhum arquivo truncado aparece na pasta.
            partial.replace(target)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            logger.exception("Falha ao copiar clip para a pasta de saída")
            raise ExportFailedError("Falha ao copiar os clips para a pasta de saída.") from exc

        exported.append(ExportedClip(sequence, target.name, target.stat().st_size))

    return exported
