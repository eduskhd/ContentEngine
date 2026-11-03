# Gaming Crop V3 — Regression Test

**Date:** 2026-11-03  
**Goal:** Confirm that fixes to `EditPlan`, `ConcatRenderRequest`, and `_render_gaming_stacked_via_ffmpeg` do not affect non-gaming (lifestyle/conversation) clips.

---

## EditPlan.from_clip() — Non-Gaming Clips

Three non-gaming clips tested (no gaming crop_config in DB):

| Clip prefix | crop_preset | main_region | x_offset |
|-------------|-------------|-------------|----------|
| 8a05039d | None | None | 188 |
| 866b1f3b | None | None | 208 |
| ffd9a4db | None | None | 99 |

**Result:** All correctly return `crop_preset=None` and `main_region=None`. The new `get_crop_config(job_id)` lookup short-circuits immediately when `gameplay_x` is not set. ✅

---

## Concat Render Path — Non-Gaming Clips

For non-gaming clips, `ConcatAdapter.render()` follows the normal path:
```
req.crop_preset is None
→ NOT "GAMING_STACKED" in crop_preset
→ Normal Concat pipeline (not _render_gaming_stacked_via_ffmpeg)
```

No code change in the normal Concat path. The 18 existing `clip_variants` with `engine_version=0.2.8+v2fix+xoff` remain valid. ✅

---

## Filter Changes — Non-Gaming Clips

No changes to:
- `_compute_crop_filter()` — face-tracking / center-crop (unchanged)
- `x_offset_to_concat_transform()` — Concat offsetX formula (unchanged)
- `keypoints_to_concat_transforms()` — multi-keypoint interpolation (unchanged)

---

## Main Pipeline (FFmpeg) — Gaming Clips

The main `render_clips_onepass()` in `engine/renderers/render_clip.py` is **not modified**.  
Gaming clips rendered via the normal pipeline continue to use the existing `crop_config` → `split_layout framing_plan` path unchanged. ✅

---

## Summary

| Test | Before | After | Result |
|------|--------|-------|--------|
| Non-gaming EditPlan.from_clip() | crop_preset=None | crop_preset=None | ✅ No regression |
| Gaming EditPlan.from_clip() | crop_preset=None (broken) | crop_preset=GAMING_STACKED_FIT | ✅ Fixed |
| Non-gaming Concat render | Normal path | Normal path | ✅ No regression |
| Gaming Concat render (via adapter) | All renders failed | Renders using actual regions | ✅ Fixed |
| Main FFmpeg pipeline | Unchanged | Unchanged | ✅ No regression |
