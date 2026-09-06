"""Configuração de logging da aplicação.

Formato JSON em produção (parseável por agregadores) e texto legível em
desenvolvimento. O `request_id` viaja por contextvar para que qualquer log
emitido durante uma requisição possa ser correlacionado sem passá-lo adiante
manualmente.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Atributos padrão de LogRecord; qualquer outro é tratado como campo extra.
_RESERVED_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


def get_request_id() -> str | None:
    return request_id_var.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key != "request_id":
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        return f"{base} [request_id={request_id}]" if request_id else base


def configure_logging(settings: Settings) -> None:
    """Instala o handler raiz. Idempotente: substitui handlers anteriores."""
    formatter: logging.Formatter
    if settings.log_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Uvicorn instala seus próprios handlers; delegamos ao root para não
    # duplicar linhas nem perder o formato JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # O access log próprio da aplicação já registra método, rota e duração.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
