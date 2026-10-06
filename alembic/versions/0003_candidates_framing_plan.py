"""Add framing_plan column to candidates

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02

Stores the JSON FramingPlan produced by engine.reframe.planner per candidate.
Allows re-renders to reuse the plan without re-running face detection.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite supports ADD COLUMN directly; no batch migration needed.
    op.execute("ALTER TABLE candidates ADD COLUMN framing_plan TEXT")


def downgrade() -> None:
    # SQLite cannot DROP COLUMN directly; batch mode rebuilds the table.
    with op.batch_alter_table("candidates", recreate="always") as batch:
        batch.drop_column("framing_plan")
