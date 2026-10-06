"""add next_attempt_at to yt_upload_sessions

Revision ID: f1bec0686e1f
Revises: 0004
Create Date: 2026-10-02 17:13:56.274250

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1bec0686e1f'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ISO-8601 UTC timestamp; NULL = retry immediately when status='pending'
    op.execute("ALTER TABLE yt_upload_sessions ADD COLUMN next_attempt_at TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_yt_sessions_next_attempt "
        "ON yt_upload_sessions(next_attempt_at)"
    )


def downgrade() -> None:
    # SQLite < 3.35 has no DROP COLUMN — column stays, ignored by downgraded code
    pass
