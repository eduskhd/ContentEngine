# Regression Report — Crop Precision RC1 Fix
**Date:** 2026-10-20  
**Phase:** 2 — Real video validation

---

## What was tested

Three IlloJuan gaming jobs with confirmed manual crops (`crop_configs` table, `validation_status = "pending"`). All three had `src_width = 1280` in the DB (preview frame dimensions) while the actual source video is 1920×1080.

| Job label | Source file | Video dims | Preview dims stored |
|---|---|---|---|
| illojuan_unban | illowanillo_dk86z8_vhhs.mp4 | 1920×1080 | 1280×720 |
| illojuan_velada | illowanillo_8zup_jkbdwa.mp4 | 1920×1080 | 1280×720 |
| illojuan_gta6 | illojuan_y7jtmhipine.mp4 | 1920×1080 | 1280×720 |

---

## Measured shift per job

The crop shift is measured as the difference between BEFORE (buggy — denormalize against 1280×720) and AFTER (fixed — denormalize against 1920×1080).

| Job | Gameplay x shift | Gameplay width shift |
|---|---|---|
| illojuan_unban | +106.2 px | +493.4 px |
| illojuan_velada | +126.7 px | +516.5 px |
| illojuan_gta6 | +126.1 px | +513.3 px |

On a 1920-wide video: the BEFORE crop was ~493–517px narrower than intended (~26% of gameplay width missing) and started ~106–127px too far to the left.

---

## Visual verification

Contact sheets (BEFORE left, AFTER right) in `contact_sheets/`:

- `illojuan_unban_SBS.jpg`
- `illojuan_velada_SBS.jpg`
- `illojuan_gta6_SBS.jpg`

BEFORE: crop starts left of the intended region, clips the right edge of the gameplay.  
AFTER: crop matches the proportional region drawn in New Job.

---

## Render results

| Job | BEFORE render | AFTER render |
|---|---|---|
| illojuan_unban | OK | OK |
| illojuan_velada | OK | OK |
| illojuan_gta6 | OK | OK |

All 6 renders produced valid MP4s. No FFmpeg errors.

---

## Formula

For a 1920×1080 video with a preview extracted at 1280×720:

```
x_shift  = norm_x × (1920 − 1280)  =  norm_x × 640
w_shift  = norm_w × (1920 − 1280)  =  norm_w × 640
```

Example (illojuan_gta6, gameplay_x ≈ 0.197):
```
x_shift  = 0.197 × 640 = 126.1 px  ✓ matches measured
w_shift  = 0.802 × 640 = 513.3 px  ✓ matches measured
```

---

## Fix location

`engine/renderers/render_clip.py` lines 143–144:

```python
# BEFORE (bug)
cw = crop_config.get("src_width") or src_w   # used 1280 for 1080p video

# AFTER (fix)
cw = src_w   # always actual video dims from ffprobe
ch = src_h
```

The `crop_config.src_width` column (1280) is the preview frame resolution and must NEVER be used for denormalization at render time.

---

## Historical clips

Clips rendered before this fix (from the same three jobs) used the incorrect pixel coordinates. Those clips are already published; they are NOT to be re-rendered automatically. User must decide if re-render is needed per clip.

---

## Test coverage for this regression

`tests/test_crop_precision.py::TestRC1ResolutionMismatch` — 5 tests verifying:
1. Normalized coords give the same selection regardless of whether they were stored during 720p or 1080p preview
2. Denormalizing the same norm coords against 1280 vs 1920 produces different (non-equal) pixel coords
3. The fix (always use actual dims) produces pixel coords proportionally equivalent to the norm rect × actual dims

The test `test_FAIL_if_renderer_uses_wrong_dims` documents the expected pixel shift if the regression is reintroduced.
