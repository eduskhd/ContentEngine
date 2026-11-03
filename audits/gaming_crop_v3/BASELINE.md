# Gaming Crop V3 — Baseline: Render State Audit

**Date:** 2026-11-03  
**Auditor:** Gaming Crop V3 session

---

## Render Paths Inventory

### Path 1: FFmpeg pure (main pipeline)

**Trigger:** `POST /jobs/{id}/generate` → `render_clips_onepass()` in `engine/renderers/render_clip.py`  
**Engine version:** Not stored (clips table has no engine_version column)  
**Gaming Stacked:** Correctly uses `main_region` / `secondary_region` from framing_plan or crop_config  
**Status:** ✅ Functional

Flow:
```
api/main.py:2131  get_crop_config(job_id)
     ↓
render_clips_onepass(crop_config=crop_cfg)
     ↓
render_clip.py:166  crop_config["gameplay_x"] → split_layout framing_plan
     ↓
render_clip.py:251  _compute_stacked_fit_filter(main_region, secondary_region)
     ↓
FFmpeg filter_complex: [main]gameplay[v0] + [face]facecam[v1] → vstack[out]
```

### Path 2: Concat pure (experimental Concat V2 path)

**Trigger:** `EditPlan.from_clip()` → `ConcatAdapter.render()`  
**Engine version:** `0.2.8+v2fix+xoff` (stored in `clip_variants.engine_version`)  
**Gaming Stacked:** Falls back to FFmpeg (Concat cannot do zone splits)  
**Status (before V3 fix):** ❌ Region data NOT propagated — both panels showed full frame  
**Status (after V3 fix):** ✅ Region data read from crop_configs and passed to FFmpeg fallback

Flow (before fix):
```
EditPlan.from_clip() — did NOT read crop_configs
     ↓
to_concat_request() — main_region=None, secondary_region=None
     ↓
ConcatAdapter.render() → _render_gaming_stacked_via_ffmpeg(req)
     ↓
BROKEN: main_region=[0,0,1920,1080], secondary_region=[0,0,1920,1080]  (full frame x2)
```

Flow (after fix):
```
EditPlan.from_clip() — reads crop_configs by job_id
     ↓
to_concat_request() — main_region=[gx,gy,gw,gh], secondary_region=[fx,fy,fw,fh]
     ↓
ConcatAdapter.render() → _render_gaming_stacked_via_ffmpeg(req)
     ↓
FIXED: uses actual gameplay/facecam regions from crop_config
```

### Path 3: FFmpeg fallback from Concat (non-gaming clips)

**Trigger:** `ConcatAdapter.render()` when Concat CLI fails or is unavailable  
**Engine version:** `{CONCAT_VERSION}+fallback` (implied by exceptions + re-raise)  
**Gaming Stacked:** N/A (separate path via `_render_gaming_stacked_via_ffmpeg`)  
**Status:** Raises `ConcatNotAvailable` / `ConcatExportFailed` — caller handles fallback

### Path 4: Re-render endpoint (FFmpeg, existing clips)

**Trigger:** `POST /clips/{id}/re-render`  
**Engine:** `burn_captions_ass()` in `engine/captions/renderer.py` (NOT `render_clips_onepass`)  
**Gaming Stacked:** NOT supported in re-render path  
**Status:** ⚠️ Known gap — re-render ignores crop_config

---

## Traceability Gap

The `clips` table lacks a `composition_engine` column. Only `clip_variants` (Concat path) stores
`engine_version`. Clips rendered via the main FFmpeg path have no engine version tracking.

**Impact:** Cannot reliably distinguish "FFmpeg pure" from "FFmpeg fallback from Concat" in the DB.
**Recommendation:** Phase 8 should add `render_engine` and `fallback_reason` to `clips` table.

---

## Gaming Clips in DB (as of 2026-11-03)

| Metric | Count |
|--------|-------|
| Jobs with crop_configs (gameplay_x set) | 10 |
| Clips from gaming jobs | ~70 |
| Clips with split_layout framing_plan in candidates table | 0 |
| clip_variants with gaming stacked renders | Unknown (engine_version query needed) |

**Finding:** All 695 candidates with framing_plan use `strategy=face_center_static` (v2).
No gaming clip has a split_layout framing_plan stored in candidates. Gaming layout data
lives exclusively in `crop_configs` table (keyed by job_id).

---

## Source Videos Available

All 10 gaming source videos confirmed on disk (58MB–8047MB).

| Job prefix | Creator | Size |
|------------|---------|------|
| efb141e5 | rickyedit | 971MB |
| 76b44f42 | miguelillo_rl | 571MB |
| 36499131 | illojuan | 337MB |
| abf14566 | illojuan_t | 8047MB |
| 40575aa4 | rickyedit | 522MB |
| afe3f6d7 | rubius_z | 824MB |
| 8dd96768 | illojuan (archivo) | 58MB |
| c6fa6cf9 | illowanillo | 104MB |
| 179734c2 | illowanillo | 324MB |
| d1834ea0 | illojuan_y | 389MB |
