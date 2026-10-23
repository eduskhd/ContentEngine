"""add render_engine to clips

Revision ID: ef29ee6b5fa6
Revises: e53dd85f8066
Create Date: 2026-10-23 11:09:28.538088

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef29ee6b5fa6'
down_revision: Union[str, Sequence[str], None] = 'e53dd85f8066'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE clips ADD COLUMN render_engine TEXT DEFAULT 'ffmpeg'")
    # Backfill: rendered clips (output_path set) → ffmpeg; phantom clips → LEGACY_UNKNOWN
    op.execute("UPDATE clips SET render_engine = 'ffmpeg' WHERE output_path IS NOT NULL")
    op.execute("UPDATE clips SET render_engine = 'LEGACY_UNKNOWN' WHERE output_path IS NULL")


def downgrade() -> None:
    # SQLite <3.35 has no DROP COLUMN — recreate table without render_engine
    op.execute("""
        CREATE TABLE clips_tmp AS
        SELECT id, job_id, candidate_id, output_path, captioned_path,
               width, height, fps, duration_s, file_size,
               technical_qa, visual_qa, qa_notes, platform_fit_scores,
               prepublish_decision, prepublish_score, caption_data, caption_settings,
               review_notes, created_at
        FROM clips
    """)
    op.execute("DROP TABLE clips")
    op.execute("ALTER TABLE clips_tmp RENAME TO clips")
