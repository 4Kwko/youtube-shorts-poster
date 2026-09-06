"""Agregação das rotas versionadas da API.

`/health` fica fora do prefixo versionado: é infraestrutura (load balancer,
docker healthcheck), não contrato de produto.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import clips, videos

api_router = APIRouter()
api_router.include_router(videos.router)
api_router.include_router(clips.router)
