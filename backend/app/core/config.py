"""Configuração da aplicação, carregada de variáveis de ambiente."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogFormat = Literal["json", "text"]

# Subdiretórios criados sob STORAGE_ROOT no startup. Cada etapa do pipeline
# escreve no seu próprio diretório para que a limpeza seja seletiva.
STORAGE_SUBDIRS: tuple[str, ...] = (
    "downloads",
    "audio",
    "clips",
    "renders",
    "transcripts",
    "subtitles",
    "thumbnails",
    "tmp",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "clipper-api"
    app_version: str = "0.1.0"
    environment: Environment = "development"
    debug: bool = False

    api_prefix: str = "/api/v1"
    # Lista separada por vírgula. Mantida como str porque pydantic-settings
    # exigiria JSON válido no .env se o campo fosse tipado como list.
    # Vite em dev (1420) e as origens que o webview do Tauri usa em produção.
    cors_origins: str = (
        "http://localhost:1420,http://127.0.0.1:1420,tauri://localhost,http://tauri.localhost"
    )

    log_level: str = "INFO"
    log_format: LogFormat = "json"

    # Timeout de chamadas ao ffprobe. Metadata é rápida; um valor alto aqui só
    # serviria para segurar um worker em um arquivo patológico.
    ffprobe_timeout_seconds: float = 30.0

    # --- Limites de ingestão ---
    # Defaults pensados para desenvolvimento: recusam cedo o que travaria uma
    # máquina local. Em produção devem subir junto com a capacidade do worker.
    max_video_duration_seconds: float = 3 * 60 * 60
    max_video_file_size_bytes: int = 2 * 1024 * 1024 * 1024
    max_video_height: int = 1080
    download_timeout_seconds: float = 1800.0
    download_socket_timeout_seconds: float = 30.0
    download_retries: int = 3

    # --- Clipping ---
    default_clip_duration_seconds: float = 90.0
    clip_timeout_seconds: float = 600.0

    # --- Renderização vertical ---
    output_width: int = 1080
    output_height: int = 1920
    render_timeout_seconds: float = 900.0

    # --- Transcrição ---
    # Defaults para CPU local. `int8` é o compromisso de qualidade/velocidade
    # que roda em máquina de desenvolvimento sem GPU.
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 5

    # --- Legendas ---
    # Blocos curtos: short-form pede leitura rápida, não parágrafo na tela.
    subtitle_max_words: int = 5
    subtitle_max_chars: int = 32
    subtitle_min_duration_seconds: float = 0.6
    subtitle_max_duration_seconds: float = 2.5
    subtitle_pause_break_seconds: float = 0.35

    # Intervalo de ociosidade do worker local entre varreduras do banco.
    worker_poll_seconds: float = 2.0

    storage_root: Path = Path("storage")
    database_url: str = "sqlite:///./storage/app.db"

    @field_validator("storage_root")
    @classmethod
    def _resolve_storage_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator(
        "max_video_duration_seconds",
        "max_video_file_size_bytes",
        "max_video_height",
        "default_clip_duration_seconds",
        "clip_timeout_seconds",
        "output_width",
        "output_height",
        "render_timeout_seconds",
        "download_timeout_seconds",
    )
    @classmethod
    def _must_be_positive(cls, value: float, info: ValidationInfo) -> float:
        if value <= 0:
            raise ValueError(f"{info.field_name} deve ser maior que zero.")
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL inválido: {value!r}. Use um de {sorted(allowed)}.")
        return level

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def storage_path(self, subdir: str) -> Path:
        """Caminho absoluto de um subdiretório conhecido de storage."""
        if subdir not in STORAGE_SUBDIRS:
            raise ValueError(f"Subdiretório de storage desconhecido: {subdir!r}")
        return self.storage_root / subdir

    def ensure_storage_dirs(self) -> None:
        for subdir in STORAGE_SUBDIRS:
            (self.storage_root / subdir).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
