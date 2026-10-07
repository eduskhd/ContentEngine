"""Add reframe_variants table for smart reframe pilot

Revision ID: 0005
Revises: f1bec0686e1f
Create Date: 2026-10-07

Stores smart-reframe analysis results and variant clip paths per clip.
These are candidate versions for review — they do not replace existing
clips or interfere with publication queues.
"""
from alembic import op

revision = "0005"
down_revision = "f1bec0686e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS reframe_variants (
        id          TEXT PRIMARY KEY,
        clip_id     TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'pending',
        strategy    TEXT,
        content_hint TEXT,
        plan_json   TEXT,
        variant_path TEXT,
        cloudinary_url TEXT,
        cloudinary_public_id TEXT,
        error       TEXT,
        analysis_time_s REAL,
        render_time_s   REAL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        FOREIGN KEY (clip_id) REFERENCES clips(id)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reframe_variants_clip_id "
        "ON reframe_variants(clip_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reframe_variants_clip_id")
    op.execute("DROP TABLE IF EXISTS reframe_variants")
