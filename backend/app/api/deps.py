"""Dependências injetáveis compartilhadas pelas rotas."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import session_scope


def get_app_settings(request: Request) -> Settings:
    """Settings da instância em execução.

    Lê de `app.state` em vez de chamar `get_settings()` diretamente: o factory
    `create_app` pode receber settings customizadas (testes, múltiplas
    instâncias) e as rotas precisam enxergar exatamente essas, não o singleton
    cacheado a partir do ambiente.
    """
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def get_session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def get_session(request: Request) -> Iterator[Session]:
    """Uma transação por requisição: commit no fim, rollback em exceção."""
    with session_scope(get_session_factory(request)) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
