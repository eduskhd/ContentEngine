# Crop Precision Repair — Final Report
**Date:** 2026-10-20 · Phases 1 + 2 complete

---

## What was wrong

The rectangle drawn in New Job was applied to the wrong pixel region in the final MP4.

**Root cause (RC1):** The frame preview is extracted from a 720p yt-dlp stream (1280×720). The actual video download is 1080p (1920×1080). The renderer was denormalizing the user's normalized [0-1] coordinates against the 720p dimensions instead of the actual 1080p video dimensions.

Example: selecting the left 80% of the frame produced a crop starting at x=128 instead of x=192 on a 1920px-wide video — a 50% shift of the intended offset.

The fix is 2 lines in `engine/renderers/render_clip.py`.

---

## What was fixed

| Issue | File | Fix |
|---|---|---|
| RC1: preview/render resolution mismatch | `engine/renderers/render_clip.py:143` | Always use `src_w`/`src_h` (actual video) for denormalization |
| RC4: validation_status gate blocked pending crops | `engine/renderers/render_clip.py:140` | Added `"pending"` to accepted statuses |

---

## What was verified

- **41/41** automated tests pass (20 new crop precision + 21 existing stacked layout)
- **4/4** synthetic grid crop tests pass (FFmpeg end-to-end)
- No regressions in existing tests

---

## Open source research conclusion

8 repositories reviewed (see `OPEN_SOURCE_RESEARCH.md`). **No new dependencies needed** for the coordinate fix.

If the canvas editor needs replacing later: **Konva.js** (MIT, actively maintained, proper DPR handling) is the right choice. Current canvas is functionally correct for coordinate math.

---

## Phase 2 — Real video validation (complete)

Three IlloJuan gaming jobs tested. All had `src_width = 1280` (preview dims) stored in DB while the actual video is 1920×1080.

| Job | x shift (BEFORE→AFTER) | w shift |
|---|---|---|
| illojuan_unban | +106.2 px | +493.4 px |
| illojuan_velada | +126.7 px | +516.5 px |
| illojuan_gta6 | +126.1 px | +513.3 px |

- 6/6 renders OK (3 BEFORE + 3 AFTER)
- 3/3 side-by-side contact sheets generated in `contact_sheets/`
- BEFORE: gameplay crop too narrow, starts left of intended region
- AFTER: crop matches the proportional region drawn in New Job

See `REGRESSION_REPORT.md` for full detail and formula.

---

## Open items (low priority, do not affect accuracy)

1. **Preview stream quality** — URL-mode preview uses 720p; rendered output is 1080p. Cosmetic only. Fix: change `api/main.py:365` to `bestvideo[height<=1080]`.
2. **Canvas DPR correction** (RC3) — HiDPI display selector quality. Cosmetic only.

---

## Files

```
experiments/crop_precision_repair/
  manifest.json                     (COMPLETE)
  ROOT_CAUSE_ANALYSIS.md
  GEOMETRY_CONTRACT.md
  CROP_ACCURACY_TESTS.md
  OPEN_SOURCE_RESEARCH.md
  LAYOUT_COMPARISON.md
  REGRESSION_REPORT.md
  PREVIEW_RENDER_PARITY.md
  FINAL_REPORT.md
  synthetic/
    make_grid_video.py
    grid_1920x1080.mp4
    verify_crop_accuracy.py
  renders/
    illojuan_unban_BEFORE.mp4
    illojuan_unban_AFTER.mp4
    illojuan_velada_BEFORE.mp4
    illojuan_velada_AFTER.mp4
    illojuan_gta6_BEFORE.mp4
    illojuan_gta6_AFTER.mp4
  contact_sheets/
    illojuan_unban_SBS.jpg
    illojuan_velada_SBS.jpg
    illojuan_gta6_SBS.jpg

tests/test_crop_precision.py         (20 new tests)
tests/test_gaming_stacked_layout.py  (21 existing tests)
engine/renderers/render_clip.py      (RC1 + RC4 fixed)
```
