"""add zones_json to crop_configs

Revision ID: ac09e6eec29e
Revises: fdfd12d4d75e
Create Date: 2026-10-21 12:41:51.676922

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac09e6eec29e'
down_revision: Union[str, Sequence[str], None] = 'fdfd12d4d75e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE crop_configs ADD COLUMN zones_json TEXT")


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN before 3.35 — recreate table without zones_json
    op.execute("""
        CREATE TABLE crop_configs_backup AS
        SELECT id, job_id, video_type, crop_mode, src_width, src_height,
               gameplay_x, gameplay_y, gameplay_w, gameplay_h,
               facecam_x, facecam_y, facecam_w, facecam_h,
               split_fraction, validation_status, created_at, updated_at,
               layout_preset, gameplay_bg
        FROM crop_configs
    """)
    op.execute("DROP TABLE crop_configs")
    op.execute("ALTER TABLE crop_configs_backup RENAME TO crop_configs")
