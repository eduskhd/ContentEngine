# Gaming Stacked Layout Tests

**Status:** INVESTIGATED — FFmpeg fallback implemented  
**Date:** 2026-11-03

---

## Objective

Implement GAMING_STACKED_FIT layout in Concat: gameplay top / webcam bottom, 4 split ratios (50/50, 60/40, 65/35, 70/30), blurred background.

---

## Concat Limitation: fill+crop zone splits

Attempted approach: two clips on separate tracks (T1/T2), each in fill mode, each with a crop fraction to mask its zone.

| Approach | Expected | Actual | Status |
|----------|----------|--------|--------|
| T1=fill+crop{bottom:0.35}, T2=fill+crop{top:0.65} | Clean 65/35 split | Incorrect zone boundaries, ~53% middle zone + black bars | FAIL |
| T1=fit+setClipTransform(scale=0.65,offsetY=-0.311), T2=(scale=0.35,offsetY=+0.578) | Two zones | Top zone in fit mode (letterboxed), bottom zone invisible | FAIL |

Track order confirmed: T2 renders **on top of** T1 (higher track = foreground). T3 > T2 > T1.

**Root cause of limitation:** Concat's `crop` fractions interact with `fill` framing in a non-trivial way. The rendered zone boundaries do not match the expected canvas pixel positions derived from the fill scale (1.7778) and crop fractions. The exact rendering formula is not documented and differs from geometric prediction. This is a Concat rendering model detail that would require binary-level debugging to resolve.

**Decision:** Gaming Stacked uses FFmpeg as the rendering engine, not Concat. This is invisible to the pipeline — the ConcatAdapter transparently delegates to FFmpeg for GAMING_STACKED_FIT requests.

---

## Solution Implemented

`integrations/concat/adapter.py`:

```python
if req.crop_preset and "GAMING_STACKED" in req.crop_preset:
    return self._render_gaming_stacked_via_ffmpeg(req)
```

`_render_gaming_stacked_via_ffmpeg()` calls `_compute_stacked_fit_filter()` from `engine/renderers/render_clip.py` (the same FFmpeg filter used by the main pipeline) then runs `ffmpeg` directly.

Returns a `ConcatRenderResult` with `engine_version = "0.2.8+ffmpeg-stacked"` to indicate the hybrid render.

---

## Split Ratios

| Ratio | top_ratio | gaming_top_ratio field |
|-------|-----------|----------------------|
| 50/50 | 0.50 | 0.50 |
| 60/40 | 0.60 | 0.60 |
| 65/35 | 0.65 | 0.65 (default) |
| 70/30 | 0.70 | 0.70 |

---

## Test Results

### Gaming Stacked — existing experiments

See `experiments/gaming_stacked_layout/` for rendered examples (from original FFmpeg GAMING_STACKED_FIT implementation, 2026-10-20):
- `00_current_fill_65_35.mp4` — baseline
- `01_stacked_fit_50_50.mp4`, `02_stacked_fit_60_40.mp4`, `03_stacked_fit_65_35.mp4`, `04_stacked_fit_70_30.mp4`
- `05_stacked_fit_65_35_blurred.mp4` — blurred bg version

These are all FFmpeg renders. The Concat adapter Gaming Stacked path uses the same FFmpeg filter.

---

## Calibration Evidence

Test file: `experiments/stack_v2_frame.png` (diagnostic with calib grid + solid red sources)  
Expected: calib top 65% / red bottom 35%  
Actual: unexpected zone positions (see image)  
Conclusion: Concat crop + fill geometry not suitable for clean zone splits.

Test file: `experiments/stack_65_35_frame.png` (SetClipTransform approach)  
Expected: scaled zones with SetClipTransform scale+offsetY  
Actual: top zone in letterbox mode, bottom zone not rendered  
Conclusion: SetClipTransform.scale does not behave as expected for sub-zone fills.
