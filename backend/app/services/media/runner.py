"""Execução de binários externos de mídia.

Todas as chamadas passam por aqui. Regras aplicadas em um único lugar:
lista de argumentos (nunca string), `shell=False`, timeout obrigatório,
stderr capturado para o log e nunca propagado ao cliente.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from app.services.media.errors import MediaProcessingError

logger = logging.getLogger(__name__)

# stderr do FFmpeg pode ter milhares de linhas; o suficiente para diagnosticar
# está sempre no fim.
_STDERR_LOG_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_command(args: list[str], *, timeout: float) -> CommandResult:
    """Executa um comando e devolve o resultado, sem levantar em exit != 0.

    Levanta `MediaProcessingError` apenas quando o processo não pôde ser
    executado ou estourou o timeout. Interpretar o exit code é responsabilidade
    de quem chama, que conhece a semântica do binário.
    """
    if not args:
        raise ValueError("Lista de argumentos vazia.")

    try:
        completed = subprocess.run(  # noqa: S603 - args é lista fixa, shell=False
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error(
            "Processo de mídia excedeu o timeout",
            extra={"binary": args[0], "timeout_seconds": timeout},
        )
        raise MediaProcessingError("O processamento de mídia excedeu o tempo limite.") from exc
    except FileNotFoundError as exc:
        logger.error("Binário de mídia não encontrado", extra={"binary": args[0]})
        raise MediaProcessingError("Dependência de mídia indisponível no servidor.") from exc
    except OSError as exc:
        logger.exception("Falha ao iniciar processo de mídia", extra={"binary": args[0]})
        raise MediaProcessingError("Não foi possível iniciar o processamento de mídia.") from exc

    if completed.returncode != 0:
        logger.warning(
            "Processo de mídia retornou exit code diferente de zero",
            extra={
                "binary": args[0],
                "returncode": completed.returncode,
                "stderr_tail": completed.stderr[-_STDERR_LOG_LIMIT:],
            },
        )

    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
