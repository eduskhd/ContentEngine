# Database Migration — Clip Variants

**Applied:** 2026-10-23  
**Alembic head:** `856de02e25ba`

---

## Migrations applied

### M-1: `ef29ee6b5fa6` — add render_engine to clips

```sql
ALTER TABLE clips ADD COLUMN render_engine TEXT DEFAULT 'ffmpeg';
UPDATE clips SET render_engine = 'ffmpeg' WHERE output_path IS NOT NULL;
UPDATE clips SET render_engine = 'LEGACY_UNKNOWN' WHERE output_path IS NULL;
```

**Result:** 729 clips → `ffmpeg`, 8 phantom clips → `LEGACY_UNKNOWN`

### M-2: `856de02e25ba` — create clip_variants table

```sql
CREATE TABLE IF NOT EXISTS clip_variants (
    id                TEXT PRIMARY KEY,
    clip_id           TEXT NOT NULL REFERENCES clips(id),
    source_variant_id TEXT REFERENCES clip_variants(id),
    render_engine     TEXT NOT NULL DEFAULT 'ffmpeg',
    engine_version    TEXT,
    edit_method       TEXT,
    project_path      TEXT,
    output_path       TEXT,
    edit_plan_json    TEXT,
    qa_status         TEXT NOT NULL DEFAULT 'PENDING',
    render_status     TEXT NOT NULL DEFAULT 'PENDING',
    duration_s        REAL,
    width             INTEGER,
    height            INTEGER,
    file_size_bytes   INTEGER,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX idx_clip_variants_clip_id ON clip_variants(clip_id);
CREATE INDEX idx_clip_variants_engine  ON clip_variants(render_engine);
```

---

## Design decisions

- `clip_variants` is separate from `clips` — no row is deleted from `clips`; variants are additive.
- A Concat render creates a row in `clip_variants` pointing to the original `clip_id`.
- `source_variant_id` allows variants of variants (e.g. re-render of a Concat version).
- `render_engine` values: `'ffmpeg'`, `'concat'`, `'LEGACY_UNKNOWN'`
- `project_path` stores the Concat project directory for re-opening/re-editing.
- `edit_plan_json` stores the serialized `EditPlan` used to generate this variant.
- Existing `clips.output_path` and `clips.captioned_path` are unchanged.

---

## API endpoints added

- `GET /clips/{clip_id}/variants` — list all variants for a clip
- `GET /engines/concat/status` — Concat availability for the UI selector

---

## DB helper functions added (engine/database.py)

- `create_clip_variant(clip_id, render_engine, output_path, ...)` → variant_id
- `get_clip_variants(clip_id)` → list of dicts
- `update_clip_variant(variant_id, **kwargs)`

---

## Rollback

Both migrations have `downgrade()` implemented. To roll back:

```powershell
python -m alembic downgrade e53dd85f8066
```

This drops `clip_variants` and recreates `clips` without `render_engine`.  
**No clip data is lost** — the column is additive and no clips are deleted.
