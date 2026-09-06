"""Smoke test do faster-whisper real.

    python scripts/smoke_whisper.py [caminho/para/audio.mp4]

Fora da suíte automatizada de propósito: baixa o modelo na primeira execução
(~75 MB para `tiny`, ~500 MB para `small`) e precisa de acesso ao Hugging Face.

Sem argumento, gera um áudio sintético com FFmpeg — útil para validar o
carregamento e a forma do retorno, não a qualidade da transcrição (um tom puro
não tem fala).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings
from app.services.transcription.backend import (
    _model_cache,
    load_model,
    transcribe_file,
)
from app.services.transcription.errors import TranscriptionError


def _synthetic_audio(directory: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("FFmpeg não encontrado e nenhum arquivo foi informado.")

    output = directory / "sample.m4a"
    subprocess.run(  # noqa: S603 - lista fixa, binário resolvido por shutil.which
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=5",
            "-c:a",
            "aac",
            "-y",
            str(output),
        ],
        check=True,
        timeout=60,
    )
    return output


def _check(condition: bool, message: str) -> bool:
    print(f"  {'OK  ' if condition else 'FALHA'} {message}")
    return condition


def main() -> int:
    settings = get_settings()
    # `tiny` baixa rápido; sobrescreva com WHISPER_MODEL para testar o real.
    print(
        f"modelo={settings.whisper_model} device={settings.whisper_device} "
        f"compute_type={settings.whisper_compute_type}"
    )

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(sys.argv[1]) if len(sys.argv) > 1 else _synthetic_audio(Path(tmp))
        if not source.is_file():
            raise SystemExit(f"Arquivo não encontrado: {source}")

        ok = True
        ok &= _check(len(_model_cache) == 0, "modelo não carregado antes do primeiro uso (lazy)")

        started = time.perf_counter()
        try:
            load_model(settings)
        except TranscriptionError as exc:
            print(f"  FALHA carregamento: [{exc.code}] {exc.message}", file=sys.stderr)
            return 1
        load_seconds = time.perf_counter() - started
        ok &= _check(len(_model_cache) == 1, f"modelo carregado e cacheado ({load_seconds:.1f}s)")

        started = time.perf_counter()
        load_model(settings)
        ok &= _check(
            time.perf_counter() - started < load_seconds / 2, "segunda carga reutiliza o cache"
        )

        started = time.perf_counter()
        result = transcribe_file(settings, source)
        print(f"  transcrição em {time.perf_counter() - started:.1f}s")

        ok &= _check(result.version == 1, "resultado normalizado (version=1)")
        ok &= _check(result.language is not None, f"idioma detectado: {result.language}")
        print(f"  segmentos: {len(result.segments)}")

        previous_end = -1.0
        increasing = True
        has_words = False
        for segment in result.segments:
            increasing &= segment.start >= previous_end - 0.001 and segment.end >= segment.start
            previous_end = segment.end
            has_words |= bool(segment.words)
            for word in segment.words:
                increasing &= segment.start - 0.001 <= word.start <= segment.end + 0.001

        if result.segments:
            ok &= _check(increasing, "timestamps crescentes e dentro dos segmentos")
            ok &= _check(has_words, "word timestamps presentes")
            preview = result.segments[0].text
            ok &= _check(preview == preview.encode("utf-8").decode("utf-8"), "texto UTF-8 válido")
            print(f"  primeiro segmento: {preview[:80]!r}")
        else:
            print("  (sem segmentos — esperado para áudio sem fala)")

    print("\nSmoke OK." if ok else "\nSmoke com falhas.")
    return 0 if ok else 1


if __name__ == "__main__":
    os.environ.setdefault("WHISPER_MODEL", "tiny")
    raise SystemExit(main())
