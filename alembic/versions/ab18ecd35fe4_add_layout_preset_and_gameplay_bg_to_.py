"""add layout_preset and gameplay_bg to crop_configs

Revision ID: ab18ecd35fe4
Revises: 8e6ea01da032
Create Date: 2026-10-20 10:12:17.603499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab18ecd35fe4'
down_revision: Union[str, Sequence[str], None] = '8e6ea01da032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE crop_configs ADD COLUMN layout_preset TEXT NOT NULL DEFAULT 'GAMING_STACKED_FIT'")
    op.execute("ALTER TABLE crop_configs ADD COLUMN gameplay_bg TEXT NOT NULL DEFAULT 'black'")


def downgrade() -> None:
    # SQLite does not support DROP COLUMN on older versions — recreate without the columns
    op.execute("""
        CREATE TABLE crop_configs_backup AS
        SELECT id, job_id, video_type, crop_mode, src_width, src_height,
               gameplay_x, gameplay_y, gameplay_w, gameplay_h,
               facecam_x, facecam_y, facecam_w, facecam_h,
               split_fraction, validation_status, created_at, updated_at
        FROM crop_configs
    """)
    op.execute("DROP TABLE crop_configs")
    op.execute("ALTER TABLE crop_configs_backup RENAME TO crop_configs")
