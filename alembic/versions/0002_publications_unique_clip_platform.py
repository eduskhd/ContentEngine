"""publications unique (clip_id, platform) excluding archived

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01

Prevents duplicate active publications for the same clip+platform.
Archived rows (status='archived') are excluded from the constraint so
superseded publications can coexist with their canonical replacement.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_pubs_clip_platform
        ON publications(clip_id, platform)
        WHERE status != 'archived'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pubs_clip_platform")
