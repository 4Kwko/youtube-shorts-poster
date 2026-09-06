"""Providers de vídeo suportados.

Allowlist de hosts. Adicionar um provider novo é adicionar uma entrada aqui —
o resto da camada de ingestão não conhece nomes de site.

`extractor_patterns` restringe quais extractors do yt-dlp podem rodar para
aquele provider. Sem isso, o extractor genérico do yt-dlp aceitaria qualquer
host e faria requisições arbitrárias: é a nossa barreira contra usar o
downloader como vetor de SSRF.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    hosts: frozenset[str]
    extractor_patterns: tuple[str, ...] = field(default=())


YOUTUBE = Provider(
    name="youtube",
    hosts=frozenset(
        {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
        }
    ),
    extractor_patterns=("Youtube.*",),
)

VIMEO = Provider(
    name="vimeo",
    hosts=frozenset({"vimeo.com", "www.vimeo.com", "player.vimeo.com"}),
    extractor_patterns=("Vimeo.*",),
)

PROVIDERS: tuple[Provider, ...] = (YOUTUBE, VIMEO)

_BY_HOST: dict[str, Provider] = {
    host: provider for provider in PROVIDERS for host in provider.hosts
}


def find_provider(host: str) -> Provider | None:
    """Provider responsável por um host, ou `None` se não suportado."""
    return _BY_HOST.get(host.lower())


def supported_hosts() -> tuple[str, ...]:
    return tuple(sorted(_BY_HOST))
