"""add finished_at to yt_upload_sessions

Revision ID: b984ce31fd8a
Revises: a720229ca710
Create Date: 2026-10-17 12:46:56.787540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b984ce31fd8a'
down_revision: Union[str, Sequence[str], None] = 'a720229ca710'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE yt_upload_sessions ADD COLUMN finished_at TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_yt_sessions_channel_finished "
        "ON yt_upload_sessions(channel_id, finished_at)"
    )


def downgrade() -> None:
    # SQLite cannot drop columns; index can be dropped
    op.execute("DROP INDEX IF EXISTS idx_yt_sessions_channel_finished")
