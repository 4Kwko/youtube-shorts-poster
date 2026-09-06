"""Engine e ciclo de vida de Session.

Sem sessão global: quem precisa de banco abre um escopo explícito. O escopo
commita no fim do bloco e faz rollback em qualquer exceção, então repositories
nunca commitam — eles só usam `flush()` quando precisam do ID gerado.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    connect_args: dict[str, Any] = {}
    if settings.database_url.startswith("sqlite"):
        # O worker de vídeo roda fora da thread da requisição.
        connect_args["check_same_thread"] = False

    engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

    if engine.dialect.name == "sqlite":
        _install_sqlite_pragmas(engine)

    return engine


def _install_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        # FKs são opt-in no SQLite; sem isso ON DELETE CASCADE é ignorado.
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL permite leitura concorrente enquanto o worker escreve.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Unidade de trabalho: commit no sucesso, rollback em qualquer exceção."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
