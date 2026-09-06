"""Entrypoint da API.

Usa application factory (`create_app`) para que os testes montem instâncias
isoladas com settings próprias, sem depender de estado global de import.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes import health as health_routes
from app.core.config import Settings, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import create_db_engine, create_session_factory
from app.services.media.binaries import MediaBinary, get_binary_status
from app.services.youtube_auth import LoginSession

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_storage_dirs()
        ffmpeg = get_binary_status(MediaBinary.FFMPEG)
        ffprobe = get_binary_status(MediaBinary.FFPROBE)
        if not (ffmpeg.available and ffprobe.available):
            logger.warning(
                "Dependências de mídia ausentes; funcionalidades de vídeo ficarão indisponíveis",
                extra={"ffmpeg": ffmpeg.available, "ffprobe": ffprobe.available},
            )
        logger.info(
            "Aplicação iniciada",
            extra={
                "environment": settings.environment,
                "version": settings.app_version,
                "ffmpeg_version": ffmpeg.version,
                "ffprobe_version": ffprobe.version,
            },
        )
        yield
        app.state.db_engine.dispose()
        logger.info("Aplicação encerrada")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        # Docs interativas ficam desligadas em produção.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.state.settings = settings
    app.state.youtube_login = LoginSession()
    # Engine criado uma vez por aplicação; conexões só abrem sob demanda.
    engine = create_db_engine(settings)
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_routes.router)
    app.include_router(api_router, prefix=settings.api_prefix)

    return app


app = create_app()
