# Root Cause Analysis — Gaming Stacked Compositor Fix

**Date:** 2026-10-20  
**Status:** FIXED  
**Engineer:** Claude Sonnet 4.6

---

## Problem Statement

Gaming clips were not displaying the stacked gameplay-over-webcam layout correctly:
- Screen not splitting according to configured percentages
- Gameplay and webcam not stacking correctly
- Webcam sometimes not appearing
- Final result not matching the layout selected in New Job

---

## Root Causes Identified

### RC1 — Coordinate Denormalization Using Wrong Resolution

**File:** `engine/renderers/render_clip.py:143`  
**Symptom:** Crop region was shifted/wrong size vs what user drew in the canvas  
**Cause:** The preview frame (used for the crop canvas) was extracted at 720p (`bestvideo[height<=720]`), but the actual downloaded video was 1080p (`bestvideo[height<=1080]`). The renderer was using `crop_config.src_width` (the preview frame dims = 1280×720) to denormalize the normalized [0-1] coordinates instead of the actual video dims (1920×1080).

**Before (bug):**
```python
cw = crop_config.get("src_width") or src_w   # BUG: used 1280 for 1080p video
ch = crop_config.get("src_height") or src_h
```

**After (fix):**
```python
cw = src_w   # always actual video dims from pipeline (from ffprobe)
ch = src_h
```

**Impact:** For a 1920×1080 video, the gameplay region was calculated at:
- Wrong: `0.197 * 1280 = 252px` (x origin)  
- Correct: `0.197 * 1920 = 378px` (x origin)
- Shift: +126px. Width: 80% of 1280=1024px vs 80% of 1920=1536px

### RC2 — FIT Mode Not Implemented (FILL Was Used)

**File:** `engine/renderers/render_clip.py` — `_compute_split_layout_filter_v11()`  
**Symptom:** Gameplay edges were being cut off (FILL=stretch to cover)  
**Cause:** The v11/v12 split layout filter used `force_original_aspect_ratio=increase` (FILL/cover) for the gameplay panel. This scales the gameplay UP until it covers the entire panel, cropping the edges.

**Before (bug):**
```python
gameplay_filter = (
    f"crop={gw}:{gh}:{gx}:{gy},"
    f"scale={TARGET_W}:{top_h}:force_original_aspect_ratio=increase,"
    f"crop={TARGET_W}:{top_h}"   # extra crop kills edges
)
```

**After (fix):** New `_compute_stacked_fit_filter()` function uses FIT mode:
```python
gameplay_filter = (
    f"crop={gw}:{gh}:{gx}:{gy},"
    f"scale={TARGET_W}:{top_h}:force_original_aspect_ratio=decrease,"  # FIT
    f"pad={TARGET_W}:{top_h}:(ow-iw)/2:(oh-ih)/2:black"               # pad edges
)
```

### RC3 — validation_status Blocking Manual Crops

**Symptom:** Jobs with gaming crop configs were falling through to center-crop framing  
**Cause:** `_manual_eligible` check required `validation_status in ("validated", "confirmed_no_preview")` but freshly saved configs had `validation_status = "pending"`.

**Fix:** Added `"pending"` to the allowed statuses:
```python
and crop_config.get("validation_status") in (
    "validated", "confirmed_no_preview", "pending",
)
```

---

## Code Path (After Fix)

```
New Job → save gaming crop config
         └→ POST /crop-configs → engine/database.py:create_crop_config()
                                  stored: gameplay_rect (normalized), facecam_rect (normalized),
                                          split_fraction, layout_preset='GAMING_STACKED_FIT',
                                          gameplay_bg, validation_status='confirmed_no_preview'

Pipeline renders clip
└→ render_clips_onepass() → _render_one()
   └→ _manual_eligible = True (gaming crop config with confirmed_no_preview)
   └→ framing_plan built with:
       - main_region = gameplay_rect * actual_video_dims   ← RC1 fixed
       - secondary_region = facecam_rect * actual_video_dims
       - preset = 'GAMING_STACKED_FIT'
       - split_fraction from crop_config
   └→ _compute_stacked_fit_filter() → filtergraph with FIT+pad   ← RC2 fixed
   └→ FFmpeg: [0:v]split=2 → crop gameplay → FIT+pad → [v0]
                           → crop facecam  → FIT+pad → [v1]
                           → vstack([v0],[v1]) → 1080×1920
```

---

## Verification

- 21/21 `test_gaming_stacked_layout.py` pass
- 20/20 `test_crop_precision.py` pass  
- 57 additional FFmpeg/integration tests pass
- 3 IlloJuan gaming jobs validated with BEFORE/AFTER renders
- 6 ratio variant renders in `experiments/gaming_stacked_layout/`
