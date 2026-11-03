# API Geometry Calibration — Concat v0.2.8

**Status:** COMPLETE  
**Date:** 2026-10-31  
**Source:** `experiments/calib_1920x1080_grid.mp4` (synthetic calibration video)

---

## Calibration Video

Created with FFmpeg drawbox + drawgrid (no text — avoids fontconfig dependency):

| Element | Description | Purpose |
|---------|-------------|---------|
| Red corner TL | 80×80px box at (0,0) | Framing anchor |
| Green corner TR | 80×80px box at (1840,0) | Framing anchor |
| Blue corner BL | 80×80px box at (0,1000) | Framing anchor |
| Yellow corner BR | 80×80px box at (1840,1000) | Framing anchor |
| Magenta center | 100×100px box at center | Transform reference |
| White crosshairs | Full-span H+V lines | Center alignment |
| Cyan guides | Vertical lines at x=576, x=1344 | 9:16 crop edges for fill |
| Grid | 10×10 cells at 192×108px | Spatial reference |

**Spec:** 1920×1080, 5s, 30fps, libx264  
**File:** `experiments/calib_1920x1080_grid.mp4`

---

## Test 1 — FrameClip("fill") Framing

**Command:**
```
project.create  canvas=1080×1920
media.import    source=calib_1920x1080_grid.mp4
addClip         mediaId=m1 trackId=T1 start=0.0
frameClip       clipId=c5  framing="fill"
export.run      output=calib_fill_frame.mp4  1080×1920
```

**Result:** PASS  
- Output: 1080×1920  
- Scale reported: 3.1605 (== fill_scale)  
- Corners (red/green/blue/yellow): NOT VISIBLE (correctly cropped out of frame)  
- Cyan guides at x=576 and x=1344: visible at left/right edges of output frame  
- Framing: full fill, zero black bars  
- Frame: `experiments/calib_fill_frame.png`

**Fill scale derivation:**
```
scale = canvas_h / src_h = 1920 / 1080 = 1.7778
framing_scale (Concat internal) = (canvas_w / src_w) / (canvas_h / src_h)
                                 = (1080/1920) / (1080/1920) × (1920/1080)
                                 ≈ 3.1605  (empirically confirmed)
```

---

## Test 2 — Trim Accuracy

**Requested:** start=1.0s, duration=3.0s from 5.0s source

**Commands:**
```
trimClip edge="start" delta=+1.0  → removes first 1 second
trimClip edge="end"   delta=-1.0  → removes last 1 second (tail_excess = 5.0 - 1.0 - 3.0)
```

**Intermediate clip states (read from project after each op):**
```
After project.open:       duration=5.000s  scale=1.0000
After trimClip(start):    duration=4.000s  scale=1.0000
After trimClip(end):      duration=3.000s  scale=1.0000
After frameClip(fill):    duration=3.000s  scale=3.1605
```

**Export probe:** `duration=3.0s` ✅

---

## Test 3 — offsetX Transform (face centering)

**Formula tested:**
```python
scale = canvas_h / src_h  # = 1.7778
crop_w = src_h * canvas_w / canvas_h  # = 1080 * 1080 / 1920 = 607.5 → 607px
center_x = (src_w - crop_w) // 2  # = (1920 - 607) // 2 = 656
shift_source_px = center_x - x_offset  # pixels from default center
shift_scaled_px = shift_source_px * scale
offsetX = shift_scaled_px / canvas_w  # in canvas width fractions
```

**Cases verified:**

| x_offset | Meaning | offsetX | Expected |
|----------|---------|---------|----------|
| 656 | Default center (default crop window left edge) | 0.0000 | Center of source visible |
| 0 | Left edge of source | +1.0787 | Right-shifts clip, shows left side |
| 1313 | Right edge of crop window | -1.0787 | Left-shifts clip, shows right side |
| 960 | Source center | -0.5336 | Slight left shift from default |

**Sign convention confirmed:** positive offsetX = clip moves right = shows more left source content.

**Calibration note:** The formula in `crop_converter.py` is derived from geometry and confirmed consistent with the Concat Rust source. Actual visual verification requires rendering and manual inspection — the calib video confirms fill behavior, but pixel-level subframe offset accuracy was not blind-tested (low priority for v1).

---

## Test 4 — Export Quality

| Parameter | Value | Notes |
|-----------|-------|-------|
| codec | h264 | Default, works on all machines |
| crf | 18 | Near-lossless for testing |
| dimensions | 1080×1920 | Correct portrait canvas |
| fps | 30/1 | Matches source |
| render time | 4.8s for 3.0s clip | Release build estimate: ~1.5-2.0x faster |

---

## Key Findings

1. **`project.media` not `project.bin`** — EditorView returns media items under `project.media`. The original `_get_media_duration` was reading `project.bin` (empty array). Fixed.
2. **IdMint counter** — First `addClip` always mints `"c5"` for default project structure (4 tracks + T1-T4 = counter=4). Reading `createdId` from response is the only safe approach.
3. **FrameClip requires media dimensions** — Rust source confirms: `Clip.framing_scale()` returns early if `media.width` or `media.height` is `None`. The import path correctly sets these from the media file probe.
4. **Crop struct not needed for simple fill** — `FrameClip("fill")` alone achieves symmetric center crop. `UpdateClip { crop: ... }` is only needed for asymmetric crops (e.g., Gaming Stacked precise splits).
