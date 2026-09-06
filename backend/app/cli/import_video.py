"""CLI de importação de vídeo.

    python -m app.cli.import_video "https://..."

Existe para exercitar a camada de ingestão sem endpoint HTTP. Imprime apenas
metadata resumida e o identificador interno — nunca caminho absoluto, cookies
ou opções internas do downloader.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.schemas.ingest import VideoSourceInfo
from app.services.ingest.errors import IngestError
from app.services.ingest.service import DOWNLOADS_SUBDIR, import_video
from app.services.ingest.urls import validate_video_url
from app.services.media.errors import MediaError

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_FAILED = 1


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "desconhecida"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_size(size: int | None) -> str:
    if size is None:
        return "desconhecido"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _format_resolution(info: VideoSourceInfo) -> str:
    if info.width is None or info.height is None:
        return "desconhecida"
    return f"{info.width}x{info.height}"


def render_summary(info: VideoSourceInfo) -> str:
    """Resumo legível. O caminho mostrado é relativo ao storage, nunca absoluto."""
    lines = [
        f"ID interno:   {info.id}",
        f"Provider:     {info.provider}",
        f"ID no provedor: {info.provider_video_id or '-'}",
        f"Título:       {info.title or '-'}",
        f"Duração:      {_format_duration(info.duration_seconds)}",
        f"Resolução:    {_format_resolution(info)}",
        f"FPS:          {info.fps if info.fps is not None else '-'}",
        f"Codecs:       {info.video_codec or '-'} / {info.audio_codec or '-'}",
        f"Container:    {info.container or '-'}",
        f"Tamanho:      {_format_size(info.file_size_bytes)}",
        f"Arquivo:      {DOWNLOADS_SUBDIR}/{info.id}/{info.local_filename}",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.import_video",
        description="Importa um vídeo por URL para o storage interno.",
    )
    parser.add_argument("url", help="URL http(s) de um provedor suportado.")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Apenas valida a URL e resolve o provider, sem baixar nada.",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="Nível de log do processo (padrão: WARNING).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    settings: Settings = get_settings()
    configure_logging(settings.model_copy(update={"log_level": args.log_level.upper()}))
    logging.getLogger(__name__).debug("CLI iniciada")

    try:
        if args.check_only:
            validated = validate_video_url(args.url)
            print(f"URL válida. Provider: {validated.provider.name}")
            if validated.had_playlist_params:
                print("Parâmetros de playlist foram removidos; será importado só o vídeo.")
            return EXIT_OK

        settings.ensure_storage_dirs()
        info = import_video(settings, args.url)
    except (IngestError, MediaError, AppError) as exc:
        # A mensagem já é a versão segura para exibição; o detalhe técnico foi
        # para o log durante a execução.
        print(f"Erro [{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_INVALID_INPUT if exc.status_code < 500 else EXIT_FAILED

    print(render_summary(info))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
