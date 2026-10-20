"""add crop_configs table

Revision ID: 8e6ea01da032
Revises: b984ce31fd8a
Create Date: 2026-10-19 10:50:20.945591

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e6ea01da032'
down_revision: Union[str, Sequence[str], None] = 'b984ce31fd8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS crop_configs (
            id TEXT PRIMARY KEY,
            job_id TEXT,
            video_type TEXT DEFAULT 'other',
            crop_mode TEXT DEFAULT 'auto',
            src_width INTEGER,
            src_height INTEGER,
            gameplay_x REAL,
            gameplay_y REAL,
            gameplay_w REAL,
            gameplay_h REAL,
            facecam_x REAL,
            facecam_y REAL,
            facecam_w REAL,
            facecam_h REAL,
            split_fraction REAL DEFAULT 0.5,
            validation_status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crop_configs_job_id ON crop_configs(job_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_crop_configs_job_id")
