"""add cancelled columns to upload_batches

Revision ID: fdfd12d4d75e
Revises: ab18ecd35fe4
Create Date: 2026-10-20 12:12:11.789864

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fdfd12d4d75e'
down_revision: Union[str, Sequence[str], None] = 'ab18ecd35fe4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE upload_batches ADD COLUMN cancelled INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE upload_batches ADD COLUMN cancelled_at TEXT")
    op.execute("ALTER TABLE upload_batches ADD COLUMN cancel_reason TEXT")
    op.execute("ALTER TABLE upload_batches ADD COLUMN archived_at TEXT")


def downgrade() -> None:
    # SQLite does not support DROP COLUMN in older versions; recreate table without cancelled cols
    op.execute("""
        CREATE TABLE upload_batches_backup AS
        SELECT id, name, channel_id, idempotency_key, paused, total_items,
               approved_privacy, created_at, updated_at
        FROM upload_batches
    """)
    op.execute("DROP TABLE upload_batches")
    op.execute("ALTER TABLE upload_batches_backup RENAME TO upload_batches")

