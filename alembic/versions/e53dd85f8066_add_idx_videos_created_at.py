"""add idx_videos_created_at

Revision ID: e53dd85f8066
Revises: ac09e6eec29e
Create Date: 2026-10-21 14:37:45.634182

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e53dd85f8066'
down_revision: Union[str, Sequence[str], None] = 'ac09e6eec29e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos(created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_videos_created_at")
