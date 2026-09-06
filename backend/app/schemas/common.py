"""Tipos compartilhados pelos schemas da API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, PlainSerializer


def _assume_utc(value: datetime) -> datetime:
    """SQLite não guarda offset: o que volta do banco é naive.

    Todo timestamp gravado é UTC (`db.base.utcnow`), então marcar o naive como
    UTC devolve o valor correto — e evita que a API emita ora com `Z`, ora sem.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_iso_z(value: datetime) -> str:
    return _assume_utc(value).isoformat().replace("+00:00", "Z")


UTCDatetime = Annotated[
    datetime,
    AfterValidator(_assume_utc),
    PlainSerializer(_to_iso_z, return_type=str, when_used="json"),
]
