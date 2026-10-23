"""create clip_variants table

Revision ID: 856de02e25ba
Revises: ef29ee6b5fa6
Create Date: 2026-10-23 11:09:32.478497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '856de02e25ba'
down_revision: Union[str, Sequence[str], None] = 'ef29ee6b5fa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS clip_variants (
            id                TEXT PRIMARY KEY,
            clip_id           TEXT NOT NULL REFERENCES clips(id),
            source_variant_id TEXT REFERENCES clip_variants(id),
            render_engine     TEXT NOT NULL DEFAULT 'ffmpeg',
            engine_version    TEXT,
            edit_method       TEXT,
            project_path      TEXT,
            output_path       TEXT,
            edit_plan_json    TEXT,
            qa_status         TEXT NOT NULL DEFAULT 'PENDING',
            render_status     TEXT NOT NULL DEFAULT 'PENDING',
            duration_s        REAL,
            width             INTEGER,
            height            INTEGER,
            file_size_bytes   INTEGER,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_clip_variants_clip_id
        ON clip_variants(clip_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_clip_variants_engine
        ON clip_variants(render_engine)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_clip_variants_engine")
    op.execute("DROP INDEX IF EXISTS idx_clip_variants_clip_id")
    op.execute("DROP TABLE IF EXISTS clip_variants")
