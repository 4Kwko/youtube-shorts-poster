"""Ambiente do Alembic.

A URL vem das Settings da aplicação, não de `alembic.ini`: um único lugar
define o banco e nenhum credencial fica versionado.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402  (importa todos os modelos)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Uma URL já definida programaticamente (testes, script de deploy) tem
# precedência; caso contrário vale DATABASE_URL das Settings.
if not config.get_main_option("sqlalchemy.url", default=None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite não suporta ALTER completo; batch mode torna as migrations
            # futuras viáveis sem trocar de banco.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
