"""Validação e normalização de URLs de vídeo.

Função pura: não faz nenhuma requisição de rede. A única coisa que toca a URL
externa é o yt-dlp, e ele só é acionado depois que a URL passou por aqui.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.ingest.errors import InvalidVideoURLError, UnsupportedVideoURLError
from app.services.ingest.providers import Provider, find_provider

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_URL_LENGTH = 2048

# Parâmetros de playlist removidos da URL antes de entregar ao yt-dlp. Com
# `noplaylist` ativo o yt-dlp já baixaria só o vídeo, mas tirar o parâmetro
# elimina a ambiguidade na origem.
_PLAYLIST_PARAMS = frozenset({"list", "index", "start_radio", "pp"})


@dataclass(frozen=True, slots=True)
class ValidatedVideoURL:
    url: str
    provider: Provider
    host: str
    had_playlist_params: bool


def _reject(message: str) -> InvalidVideoURLError:
    return InvalidVideoURLError(message)


def _is_ip_literal(host: str) -> bool:
    candidate = host.strip("[]")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return True


def strip_playlist_params(url: str) -> tuple[str, bool]:
    """Remove parâmetros de playlist. Retorna a URL limpa e se algo foi removido."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    filtered = [(key, value) for key, value in query if key.lower() not in _PLAYLIST_PARAMS]

    if len(filtered) == len(query):
        return url, False

    return urlunsplit(parts._replace(query=urlencode(filtered))), True


def validate_video_url(raw_url: str) -> ValidatedVideoURL:
    """Valida uma URL vinda de fora e resolve o provider.

    Levanta `InvalidVideoURLError` para qualquer coisa que não seja uma URL
    http(s) bem formada e `UnsupportedVideoURLError` para hosts fora da
    allowlist.
    """
    if not isinstance(raw_url, str):
        raise _reject("URL deve ser uma string.")

    url = raw_url.strip()
    if not url:
        raise _reject("URL vazia.")
    if len(url) > MAX_URL_LENGTH:
        raise _reject("URL excede o tamanho máximo permitido.")
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise _reject("URL contém caracteres de controle.")

    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise _reject("URL malformada.") from exc

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        # Cobre file://, ftp://, data:, javascript: e caminho local sem esquema.
        raise _reject("Apenas URLs http e https são aceitas.")

    if parts.username or parts.password:
        raise _reject("URL não pode conter credenciais.")

    try:
        host = parts.hostname or ""
    except ValueError as exc:
        raise _reject("URL malformada.") from exc

    if not host:
        raise _reject("URL sem host.")

    # Host literal por IP nunca é um provider legítimo e é o formato usual de
    # tentativa de SSRF (127.0.0.1, 169.254.169.254, IPv6 loopback).
    if _is_ip_literal(host):
        raise _reject("URL por endereço IP não é aceita.")

    try:
        port = parts.port
    except ValueError as exc:
        raise _reject("Porta inválida na URL.") from exc

    if port is not None and port not in (80, 443):
        raise _reject("Porta não permitida na URL.")

    provider = find_provider(host)
    if provider is None:
        raise UnsupportedVideoURLError("Este site não é suportado para importação.")

    clean_url, had_playlist = strip_playlist_params(url)

    return ValidatedVideoURL(
        url=clean_url,
        provider=provider,
        host=host.lower(),
        had_playlist_params=had_playlist,
    )
