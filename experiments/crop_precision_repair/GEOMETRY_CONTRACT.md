# Geometry Contract — ContentEngine Crop Pipeline
**Date:** 2026-10-20  
**Version:** 1.0

---

## Canonical coordinate format

All crop regions are stored and transported as **normalized coordinates**:

```
[x, y, w, h]  ∈ [0.0, 1.0]
```

Where:
- `x, y` — top-left corner of the region as a fraction of the source frame width/height
- `w, h` — region width/height as a fraction of the source frame

**Invariant:** normalized coords are resolution-independent. The same normalized region applied to 720p or 1080p video of identical aspect ratio selects the same visual content.

---

## Coordinate lifecycle

```
STAGE              FORMAT          DIMENSIONS USED
─────────────────────────────────────────────────────────────────
Canvas draw        CSS pixels      canvas.width × canvas.height
                   (= wrap.clientWidth × img-AR-height)

Normalize          norm [0-1]      px / canvas.width|height
  ↓ stored in _njUrlCropState as {x,y,w,h}

API POST           norm [0-1]      sent with src_width/src_height
  /crop-configs                    (reference only, NOT for denorm)

DB storage         norm [0-1]      crop_configs.gameplay_x/y/w/h
  crop_configs

Renderer           pixel space     ACTUAL video dims from pipeline
  render_clip.py                   src_w, src_h (from videos table
  denormalization                  via ffprobe on downloaded file)

FFmpeg crop        pixel space     source video coded dimensions
  filter                          e.g. crop=1536:1080:192:0
```

---

## Rules

### Rule 1: Denormalize always against actual video dims

```python
# CORRECT
cw, ch = src_w, src_h   # from pipeline (ffprobe on downloaded file)

# WRONG — was the RC1 bug
cw = crop_config.get("src_width") or src_w   # preview frame dims
```

The `src_width/src_height` stored in `crop_configs` is the preview frame resolution (from the 720p yt-dlp stream). It must NEVER be used for denormalization in the renderer.

### Rule 2: One normalization, one denormalization

Normalized coords must be computed exactly once (at canvas draw time) and denormalized exactly once (at render time). No intermediate re-scaling.

### Rule 3: Manual selection has absolute priority

When `crop_config.crop_mode == "manual"` and both rects are present, the manual crop overrides all auto-generated framing plans. No automatic planner can modify the manual selection.

### Rule 4: Crop and layout are independent stages

Region extraction (FFmpeg `crop=`) uses the raw source pixel coords.  
Layout composition (`scale=`, `pad=`, `vstack=`) adapts the extracted region to the target canvas.  
Neither stage may silently modify the other's parameters.

### Rule 5: Validation gate

A manual crop with `validation_status = "pending"` is still applied if both rects are present. The validator does not block rendering — it is a UI signal only.

---

## What `src_width/src_height` in crop_configs means

This field records the dimensions of the **preview frame** used by the user during selection. It is:
- Correct reference for the preview endpoint (runs FFmpeg on the same stream)
- **NOT** the actual video dimensions for the renderer

Do not repurpose this field for denormalization. It exists for diagnostic purposes only.

---

## FFmpeg filter contract

The filter functions receive and produce pixel-space coordinates:

```python
_compute_stacked_fit_filter(
    main_region: [x_px, y_px, w_px, h_px],   # gameplay in source pixels
    secondary_region: [x_px, y_px, w_px, h_px],  # facecam in source pixels
    src_w: int,   # source video width (for clamping)
    src_h: int,   # source video height (for clamping)
    top_fraction: float = 0.65,
    bg: str = "black",
) -> str  # FFmpeg filter_complex string with [out] output
```

Output: always `1080×1920` (TARGET_W × TARGET_H).  
No function may produce coordinates outside `[0, src_w)` × `[0, src_h)`.

---

## Preview parity

After the RC1 fix, preview and render are equivalent for same-AR content:

- Preview runs on the 720p yt-dlp stream → pixel coords computed with 720p dims
- Render runs on the 1080p download → pixel coords computed with 1080p dims
- Both reference the same proportional region (normalized coords are AR-invariant)
- Visual output is geometrically identical for 16:9 source videos
