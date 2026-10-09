"""add framing_plan to clips

Revision ID: a720229ca710
Revises: 0006
Create Date: 2026-10-09 11:16:21.412104

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a720229ca710'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE clips ADD COLUMN framing_plan TEXT")


def downgrade() -> None:
    # SQLite does not support DROP COLUMN before 3.35; recreate is required.
    # For simplicity we no-op downgrade — the column is nullable so it's harmless.
    pass
