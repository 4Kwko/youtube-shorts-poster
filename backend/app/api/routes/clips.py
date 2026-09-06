"""Rotas de clips: metadata, reprodução e download do render final.

O cliente nunca informa caminho. Ele passa `clip_id`; o caminho sai do
`rendered_file_key` gravado no banco, resolvido pelo helper de storage.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import SessionDep, SettingsDep
from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_request_id
from app.models.clip import Clip
from app.models.enums import ClipStatus
from app.repositories import ClipRepository
from app.schemas.clip import ClipResponse
from app.schemas.errors import ErrorDetail, ErrorResponse
from app.services.rendering import render_path
from app.utils.ranges import ByteRange, RangeNotSatisfiableError, parse_range_header

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])

MEDIA_CONTENT_TYPE = "video/mp4"
# 512 KiB: grande o bastante para não picotar o streaming, pequeno o bastante
# para o processo não segurar o arquivo inteiro em memória.
CHUNK_SIZE = 512 * 1024


class ClipNotRenderedError(AppError):
    """O clip existe mas ainda não tem render disponível."""

    status_code = 409
    code = "clip_not_rendered"


class ClipMediaMissingError(AppError):
    """O banco aponta para um render que não está no disco."""

    status_code = 410
    code = "clip_media_missing"


def _load_clip(session: SessionDep, clip_id: str) -> Clip:
    clip = ClipRepository(session).get_by_id(clip_id)
    if clip is None:
        raise NotFoundError("Clip não encontrado.")
    return clip


def _resolve_media(settings: Settings, clip: Clip) -> Path:
    if clip.status is not ClipStatus.RENDERED or not clip.rendered_file_key:
        raise ClipNotRenderedError("O clip ainda não foi renderizado.")

    try:
        path = render_path(settings, clip.rendered_file_key)
    except ValueError as exc:
        # Chave inconsistente no banco; o cliente não precisa saber o motivo.
        logger.error("rendered_file_key inválido", extra={"clip_id": clip.id})
        raise ClipMediaMissingError("Arquivo do clip indisponível.") from exc

    if not path.is_file():
        logger.warning("Render ausente no storage", extra={"clip_id": clip.id})
        raise ClipMediaMissingError("Arquivo do clip indisponível.")

    return path


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    """Lê em blocos, sempre fechando o arquivo ao fim da resposta."""
    remaining = length
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _range_not_satisfiable(file_size: int) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code="range_not_satisfiable",
            message="O intervalo solicitado está fora do arquivo.",
        ),
        request_id=get_request_id(),
    )
    return JSONResponse(
        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
        content=body.model_dump(mode="json"),
        # Informa o tamanho real para o cliente refazer o pedido.
        headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
    )


def _stream(path: Path, request: Request, *, disposition: str | None = None) -> Response:
    file_size = path.stat().st_size

    try:
        byte_range: ByteRange | None = parse_range_header(request.headers.get("range"), file_size)
    except RangeNotSatisfiableError:
        return _range_not_satisfiable(file_size)

    start = byte_range.start if byte_range else 0
    length = byte_range.length if byte_range else file_size

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
    if byte_range is not None:
        headers["Content-Range"] = byte_range.content_range(file_size)
    if disposition is not None:
        headers["Content-Disposition"] = disposition

    return StreamingResponse(
        _iter_file(path, start, length),
        status_code=status.HTTP_206_PARTIAL_CONTENT if byte_range else status.HTTP_200_OK,
        media_type=MEDIA_CONTENT_TYPE,
        headers=headers,
    )


def download_filename(clip: Clip) -> str:
    """Nome previsível e seguro.

    Derivado só de `sequence`: título do provedor é texto arbitrário e não tem
    o que fazer num nome de arquivo.
    """
    return f"clip-{clip.sequence:03d}.mp4"


@router.get("/{clip_id}", response_model=ClipResponse, summary="Dados de um clip")
def get_clip(clip_id: str, session: SessionDep) -> ClipResponse:
    return ClipResponse.model_validate(_load_clip(session, clip_id))


@router.get(
    "/{clip_id}/media",
    summary="Reproduz o render final",
    description="Suporta HTTP Range para seek. 206 quando há Range, 200 caso contrário.",
    response_class=StreamingResponse,
    responses={
        200: {"content": {MEDIA_CONTENT_TYPE: {}}, "description": "Arquivo completo"},
        206: {"content": {MEDIA_CONTENT_TYPE: {}}, "description": "Trecho solicitado"},
        416: {"description": "Range fora do arquivo"},
    },
)
def get_clip_media(
    clip_id: str, request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    clip = _load_clip(session, clip_id)
    return _stream(_resolve_media(settings, clip), request)


@router.get(
    "/{clip_id}/download",
    summary="Baixa o render final",
    response_class=StreamingResponse,
    responses={200: {"content": {MEDIA_CONTENT_TYPE: {}}, "description": "Arquivo para download"}},
)
def download_clip(
    clip_id: str, request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    clip = _load_clip(session, clip_id)
    path = _resolve_media(settings, clip)
    return _stream(path, request, disposition=f'attachment; filename="{download_filename(clip)}"')
