"""Handlers globais de exceção.

Objetivo: toda resposta de erro tem o mesmo shape (`ErrorResponse`) e nenhuma
delas vaza stack trace, caminho de arquivo ou detalhe interno do servidor. O
diagnóstico fica no log, correlacionado pelo `request_id` devolvido ao cliente.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import get_request_id
from app.schemas.errors import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def _resolve_request_id(request: Request) -> str | None:
    # A contextvar já foi resetada quando o handler de exceção não tratada roda,
    # por isso o scope da requisição é a fonte primária.
    scoped = getattr(request.state, "request_id", None)
    if isinstance(scoped, str):
        return scoped
    return get_request_id()


def _json_error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details or {}),
        request_id=_resolve_request_id(request),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning(
        "Erro de aplicação: %s",
        exc.message,
        extra={"error_code": exc.code, "path": request.url.path},
    )
    return _json_error(request, exc.status_code, exc.code, exc.message, exc.details)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == status.HTTP_404_NOT_FOUND else "http_error"
    detail = exc.detail if isinstance(exc.detail, str) else "Requisição inválida."
    return _json_error(request, exc.status_code, code, detail)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # `errors()` pode conter o valor enviado pelo cliente; devolvemos apenas
    # localização e motivo para não ecoar payload arbitrário de volta.
    fields = [
        {"field": ".".join(str(part) for part in error["loc"]), "reason": error["msg"]}
        for error in exc.errors()
    ]
    logger.info("Payload inválido", extra={"path": request.url.path, "fields": fields})
    return _json_error(
        request,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "validation_error",
        "Dados de entrada inválidos.",
        {"fields": fields},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Exceção não tratada",
        extra={"path": request.url.path, "method": request.method},
    )
    return _json_error(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Erro interno. Use o request_id ao reportar o problema.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
