"""Add metadata tracking columns to publications

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02

meta_version tracks how title/caption were generated: "llm_v1", "deterministic_v1", "manual".
title_prev / caption_prev hold the previous values so regeneration is recoverable.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE publications ADD COLUMN meta_version TEXT")
    op.execute("ALTER TABLE publications ADD COLUMN title_prev TEXT")
    op.execute("ALTER TABLE publications ADD COLUMN caption_prev TEXT")


def downgrade() -> None:
    with op.batch_alter_table("publications", recreate="always") as batch:
        batch.drop_column("meta_version")
        batch.drop_column("title_prev")
        batch.drop_column("caption_prev")
