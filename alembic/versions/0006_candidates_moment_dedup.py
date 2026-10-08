"""Add moment deduplication columns to candidates

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08

moment_group_id: shared UUID for all candidates covering the same narrative
  moment in a video. NULL for singletons. Set by the post-scoring dedup step
  (pipeline step 7.75).

group_evidence: JSON capturing why candidates were grouped — shared words,
  overlap ratio, winner criteria — for audit and UI detail view.
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE candidates ADD COLUMN moment_group_id TEXT")
    op.execute("ALTER TABLE candidates ADD COLUMN group_evidence TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidates_moment_group "
        "ON candidates(moment_group_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_candidates_moment_group")
    with op.batch_alter_table("candidates", recreate="always") as batch:
        batch.drop_column("moment_group_id")
        batch.drop_column("group_evidence")
