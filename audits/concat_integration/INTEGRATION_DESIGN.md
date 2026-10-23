# Concat Integration Design

**Version:** Draft 1.0  
**Date:** 2026-10-23

---

## Architecture

```
Content Engine Pipeline (FFmpeg, unchanged)
          │
          └─ render_engine == "concat" in job metadata
                    │
                    ▼
          integrations/concat/
          ├── __init__.py          concat_available(), get_adapter(), get_availability_status()
          ├── adapter.py           ConcatAdapter: high-level render workflow
          ├── mcp_client.py        MCPClient: stdio JSON-RPC subprocess wrapper
          ├── crop_converter.py    x_offset → Concat offsetX fraction
          ├── exceptions.py        ConcatNotAvailable, ConcatTimeout, ConcatMCPError
          └── (edit_plan.py)       EditPlan dataclass — Phase 7
```

---

## Feature flag

`engine/config.py`:
```python
concat_enabled: bool = False           # NEVER True in production until Phase 10 passes
concat_exe_path: str = r"..."          # default Windows install path
concat_projects_dir: str = r"..."      # working dir for Concat projects
concat_mcp_timeout_s: float = 120.0
concat_export_timeout_s: float = 600.0
```

Concat is **always disabled by default**. Enabling requires:
1. Setting `concat_enabled = True`
2. Verifying Smart App Control compatibility
3. Verifying `concat.exe` responds to `--mcp headless`

---

## Render workflow (per clip)

```
ConcatAdapter.render(ConcatRenderRequest)
  │
  ├─ MCPClient.start()       → launch concat.exe --mcp headless
  ├─ project_create          → new project dir per clip (avoids concat.lock conflicts)
  ├─ media_import            → import source video
  ├─ track_add               → add video track
  ├─ clip_add                → add clip to timeline at t=0
  ├─ clip_trim               → set in/out points (start_s, duration_s)
  ├─ clip_frame("fill")      → landscape → portrait fill
  ├─ clip_transform          → offsetX to center detected subject
  ├─ keyframe_set            → per-scene offsets if multi-scene
  ├─ [captions_add]          → if caption_words provided (fallback to title_add)
  ├─ project_save
  ├─ export_start            → 1080×1920 h264
  ├─ export_status (poll)    → wait with timeout + circuit breaker
  └─ MCPClient.stop()
```

---

## Crop conversion

Source: 1920×1080 landscape, subject at `x_offset` pixels from left  
Target: 1080×1920 portrait canvas

Using `clip_frame("fill")`:
- Scale factor: 1920/1080 = 1.778
- Scaled source width: 1920 × 1.778 = 3413px
- Default center: 3413/2 = 1706px
- Subject center in scaled: x_offset × 1.778
- Pixel shift from default: (x_offset × 1.778) − 1706
- `offsetX` fraction: −pixel_shift / 1080

**NOTE:** Sign convention and exact behavior of `offsetX` must be calibrated during Phase 6 experiments.

---

## Captions strategy

`captions_add` is in the MCP tool list but its parameters are NOT documented.

Strategy for Phase 6:
1. Attempt `captions_add` with `words` array (same format as pipeline)
2. If it fails (MCP error), fall back to per-segment `title_add` calls
3. Document which approach works and at what quality level
4. For Phase 6 comparison, the alternative is: pass FFmpeg-captioned video to Concat (import already-subtitled file)

Word-level karaoke-style captions (ASS format) are a FFmpeg pipeline strength. Concat captions may differ in style.

---

## Failure isolation

All Concat failures are non-fatal to the main pipeline:
- `ConcatNotAvailable` → logged, no variant created, no job failure
- `ConcatTimeout` → logged, export cancelled if possible
- `ConcatMCPError` → logged with error code and data
- File system errors → logged, existing clips unaffected

A Concat variant failure NEVER marks the parent `clip` as failed.

---

## New Job selector

New Job form includes an engine radio button:
- FFmpeg (default, always active)
- Concat (disabled if not available, shows status: "checking…" / "(disabled)" / "(v0.2.8) experimental")

The selection is passed as `render_engine` in the `/jobs/from-url` payload and stored in `jobs.metadata`.

---

## Library integration (Phase 5 — pending)

Each clip card will show a small engine badge: **FFmpeg** / **Concat** / **Legacy**  
Variants accessible via clip detail view: list of `clip_variants` with engine, version, QA status.  
Actions: "Create Concat version", "Compare versions", "Set as preferred".

---

## Publishing protection (Phase 9)

All existing publications point to `clips.output_path`.  
`clip_variants.output_path` is a separate file — publications are never automatically updated.  
"Preferred" version is informational only — publishing pipeline always reads from `clips`.  
To publish a Concat variant: explicit user action to promote it to the canonical `clips.output_path` (Phase 9 — requires authorization design).
