"""Middleware de contexto de requisição."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_var

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Atribui um request_id, registra o acesso e mede a duração."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming: str | None = request.headers.get(REQUEST_ID_HEADER)
        # Só reaproveita o header do cliente se for um UUID: evita injeção de
        # texto arbitrário nos logs.
        request_id = incoming if incoming is not None and _is_uuid(incoming) else str(uuid.uuid4())

        token = request_id_var.set(request_id)
        # Também no scope: em caso de exceção não tratada, o handler global roda
        # fora deste middleware, quando a contextvar já foi resetada.
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # O handler global monta a resposta; aqui só garantimos que a
            # falha apareça no access log com a duração.
            duration_ms = (time.perf_counter() - started) * 1000
            logger.error(
                "%s %s -> exceção",
                request.method,
                request.url.path,
                extra={"duration_ms": round(duration_ms, 2)},
            )
            raise
        else:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_var.reset(token)


def _is_uuid(value: str) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
