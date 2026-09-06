"""video settings json

Revision ID: ffc574eead66
Revises: a7fba013916b
Create Date: 2026-09-05 02:24:36.235969

"""
from typing import Sequence, Union

from alembic import op
import json

import sqlalchemy as sa

from app.models.enums import VerticalLayout
from app.schemas.settings import VideoSettings

# Congelado no momento da migration: mudanças futuras no schema não devem
# reescrever o backfill de quem já rodou este upgrade.
DEFAULT_SETTINGS = VideoSettings().model_dump(mode="json")
DEFAULT_LAYOUT_VALUE = DEFAULT_SETTINGS["layout"]


# revision identifiers, used by Alembic.
revision: str = 'ffc574eead66'
down_revision: Union[str, Sequence[str], None] = 'a7fba013916b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adiciona `settings` e faz backfill a partir das colunas legadas.

    Migration conservadora: `clip_duration_seconds`, `layout` e
    `subtitle_font_size` continuam existindo e sendo escritas. A remoção delas
    fica para um patch posterior, depois de a leitura pelo JSON estar validada.
    """
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("settings", sa.JSON(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, clip_duration_seconds, layout, subtitle_font_size FROM videos"
        )
    ).fetchall()

    for row in rows:
        # O enum é gravado pelo nome (BLURRED_4_3); o JSON usa o valor.
        layout = VerticalLayout[row.layout].value if row.layout else DEFAULT_LAYOUT_VALUE
        settings = DEFAULT_SETTINGS | {
            "clip_duration_seconds": row.clip_duration_seconds,
            "layout": layout,
            "subtitle_font_size": row.subtitle_font_size,
        }
        connection.execute(
            sa.text("UPDATE videos SET settings = :settings WHERE id = :id"),
            {"settings": json.dumps(settings), "id": row.id},
        )


def downgrade() -> None:
    """Remove `settings`. As colunas legadas seguem com os mesmos valores."""
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_column("settings")
