# Gaming Crop V3 — Final Report

**Date:** 2026-11-03  
**Scope:** Diagnosis and fix of gaming clip editorial quality in the Concat adapter path  
**Status:** ✅ All critical bugs fixed. A/B renders verified.

---

## Executive Summary

Gaming clips rendered via the Concat adapter path had a critical editorial defect: both the top and bottom panels of the stacked layout showed identical content (the full 1920×1080 source frame). This was caused by a chain of 7 bugs across 4 files. All bugs have been identified and fixed. A/B comparison renders confirm the fix: each panel now shows its intended region (streamer face/overlay vs. main gameplay).

---

## Bugs Fixed

| # | File | Bug | Severity |
|---|------|-----|----------|
| 1 | `adapter.py` | `_render_gaming_stacked_via_ffmpeg` hardcoded full-frame for both panels | CRITICAL |
| 2 | `adapter.py` | `ConcatRenderRequest` missing `main_region`/`secondary_region` fields | CRITICAL |
| 3 | `edit_plan.py` | `EditPlan.from_clip()` ignored `crop_configs` table | CRITICAL |
| 4 | `edit_plan.py` | `EditPlan` missing `main_region`/`secondary_region`/`gaming_top_ratio` fields | MEDIUM |
| 5 | `adapter.py` | `detect_encoder()` returns 3-tuple but unpacked as 2 | HIGH (runtime crash) |
| 6 | `crop_converter.py` | Module docstring said "face center" instead of "crop left edge" | LOW (docs) |
| 7 | `adapter.py` | Used `-vf` with a `filter_complex` graph (should be `-filter_complex -map [out]`) | HIGH (runtime crash) |

---

## Data Flow After Fix

```
EditPlan.from_clip(clip_id)
  ↓ reads candidates.framing_plan (face_center_static for all current clips)
  ↓ reads crop_configs WHERE job_id = clip.job_id
  ↓ if gameplay_x set: computes main_region, secondary_region (source pixels)
  ↓ sets crop_preset = layout_preset, gaming_top_ratio = split_fraction
  ↓
EditPlan.to_concat_request()
  ↓ passes main_region, secondary_region, gaming_top_ratio → ConcatRenderRequest
  ↓
ConcatAdapter.render(req)
  → detects "GAMING_STACKED" in req.crop_preset
  → calls _render_gaming_stacked_via_ffmpeg(req)
    ↓ uses req.main_region, req.secondary_region (not full-frame fallback)
    ↓ calls _compute_stacked_fit_filter(main_region, secondary_region, ...)
    ↓ uses -filter_complex {stacked_filter} -map [out]  (not -vf)
    ↓ detect_encoder() → encoder, enc_opts, _tier
    ↓ FFmpeg render with actual gaming regions ✅
```

---

## A/B Comparison Results

3 clips from 3 different gaming jobs:

| Clip | A (broken) | B (fixed) | Visual |
|------|-----------|-----------|--------|
| rickyedit 36.6s | 20.4MB 37.7s | 26.3MB 33.9s | A: duplicate frame; B: overlay + gameplay |
| miguelillo 33.3s | 40.9MB 27.7s | 28.8MB 26.0s | A: duplicate frame; B: overlay + gameplay |
| illojuan 31.1s | 5.9MB 30.2s | 7.6MB 28.9s | A: duplicate frame; B: overlay + gameplay |

All 6 renders succeeded. ✅

---

## Region Configuration Pattern

All 10 gaming jobs use the same layout pattern (user-defined via dashboard):
- `main_region` (top 65% panel) = small left-side region (streamer face/reaction overlay on screen)
- `secondary_region` (bottom 35% panel) = large right-side region (main gameplay view)

This is an editorial choice optimized for reaction content. The field names in `crop_configs` (`gameplay_x` = small region, `facecam_x` = large region) are counterintuitive but semantically consistent with how the user set them up.

---

## Regression Tests

- Non-gaming clips: `crop_preset=None`, `main_region=None` — unchanged ✅
- Main FFmpeg pipeline: not modified — unchanged ✅
- Existing Concat clip_variants (18 records, engine_version=0.2.8+v2fix+xoff): not affected ✅

---

## Remaining Gaps (Not Fixed in V3)

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| `clips` table has no `render_engine`/`engine_version` column | Cannot distinguish FFmpeg vs Concat renders in main clips | Add Alembic migration for Phase 8 |
| Re-render endpoint ignores `crop_configs` | Gaming clips re-rendered via `/clips/{id}/re-render` lose gaming layout | Extend re-render path to read crop_configs |
| No scene transition detection | Webcam disappearance not detected | Phase 6 future work |
| Concat can't do zone splits natively | Gaming stacked always uses FFmpeg fallback | Architectural limitation of Concat v0.2.8 |

---

## Files Changed

| File | Change |
|------|--------|
| `integrations/concat/adapter.py` | Added `main_region`/`secondary_region` to `ConcatRenderRequest`; fixed `_render_gaming_stacked_via_ffmpeg` regions + filter_complex + detect_encoder unpack |
| `integrations/concat/edit_plan.py` | Added `main_region`/`secondary_region`/`gaming_top_ratio` to `EditPlan`; `from_clip()` reads crop_configs; `to_concat_request()` passes all three |
| `integrations/concat/crop_converter.py` | Fixed module docstring: x_offset is crop LEFT EDGE, not face center |

---

## Audit Documents

```
audits/gaming_crop_v3/
├── BASELINE.md           — All render paths documented (FFmpeg pure/Concat/fallback)
├── ROOT_CAUSES.md        — 7 bugs, all fixed
├── GEOMETRY_TESTS.md     — Region coordinate conversion verification
├── RENDER_COMPARISON.md  — A/B results (3 clips × 2 variants = 6 renders)
├── REGRESSION.md         — Non-gaming clip regression checks
├── FINAL_REPORT.md       — This file
└── renders/              — 6 MP4 files + ab_results.json
```
