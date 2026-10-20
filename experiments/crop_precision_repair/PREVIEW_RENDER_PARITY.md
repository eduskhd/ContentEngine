# Preview / Render Parity Analysis
**Date:** 2026-10-20

---

## Status after RC1 fix: RESOLVED for coordinate accuracy

After the RC1 fix, preview and render share the same **normalized coordinates** as the canonical representation. The renderer always denormalizes against the actual video dimensions (1920×1080), regardless of what resolution was used to extract the preview frame.

This means: a selection drawn on a 720p preview thumbnail produces the correct 1080p crop in the final render.

---

## Remaining gap: visual WYSIWYG

The user still sees a 720p frame when drawing the crop rectangle in New Job (URL mode). The rendered output is the same proportional region of the 1080p video. Coordinate math is correct, but the preview image is lower resolution than the final render.

**Impact:** None on crop accuracy. The user may notice a quality difference between what they see while drawing and the final rendered clip. This is cosmetic only.

**Fix (low priority):** Change `api/main.py:365` to use `bestvideo[height<=1080]` for frame extraction instead of `bestvideo[height<=720]`. This would make the preview image match the exact frame that will be cropped.

---

## What "parity" means in normalized coordinates

```
User draws rect on 1280×720 preview:
  canvas_x=213,  canvas_y=6,  canvas_w=987,  canvas_h=683

Stored as normalized [0-1]:
  norm_x=0.166,  norm_y=0.009,  norm_w=0.771,  norm_h=0.950

Renderer (AFTER fix) denormalizes against actual 1920×1080:
  px_x = 0.166 × 1920 = 318.7 px  (≈ 319)
  px_y = 0.009 × 1080 = 9.7 px    (≈ 10)
  px_w = 0.771 × 1920 = 1480.3 px (≈ 1480)
  px_h = 0.950 × 1080 = 1026.0 px (≈ 1026)

The relative region is identical: same 16.6% from left edge, 
same 77.1% of frame width — which is the correct gameplay zone.
```

Compare with the bug (BEFORE fix):
```
Renderer (BEFORE fix) denormalized against preview dims 1280×720:
  px_x = 0.166 × 1280 = 212.5 px  (wrong — 106 px too far left)
  px_w = 0.771 × 1280 = 987.1 px  (wrong — 493 px too narrow)
```

The BEFORE case was cropping a **different region** of the video than the user selected. Fixed.

---

## Test confirming parity

`tests/test_crop_precision.py::TestPreviewRenderParity`:
- Verifies that the same normalized rect applied to 720p produces 720-proportional pixels and applied to 1080p produces 1.5× larger pixels (correct scaling)
- Verifies that a 1280-denormalized crop does NOT equal a 1920-denormalized crop (documents the bug)

---

## Summary

| Aspect | Status |
|---|---|
| Coordinate accuracy (RC1) | FIXED — correct region cropped |
| Normalized storage | CORRECT — [0-1] coords in DB |
| Denormalization at render time | FIXED — uses src_w/src_h |
| Visual preview quality (WYSIWYG) | LOW PRIORITY — 720p preview vs 1080p render |
| DPR correction on HiDPI displays (RC3) | LOW PRIORITY — cosmetic |
