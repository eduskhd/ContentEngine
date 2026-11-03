# Composition Model — Concat V2

**Status:** IMPLEMENTED  
**Date:** 2026-10-31

---

## Overview

The ContentEngine Concat integration uses an `EditPlan` dataclass as a motor-independent layer between the pipeline and the Concat API. The same plan description can (in principle) drive FFmpeg or Concat — though in practice only Concat uses it.

---

## EditPlan Fields

```python
@dataclass
class EditPlan:
    # Source
    source_path: str       # absolute path to source video file
    start_s: float         # trim start in source timecode seconds
    duration_s: float      # clip duration in seconds

    # Video geometry
    src_w: int = 1920      # source width
    src_h: int = 1080      # source height  
    canvas_w: int = 1080   # output canvas width (portrait)
    canvas_h: int = 1920   # output canvas height (portrait)
    fps: int = 30

    # Layout
    framing: str = "fill"  # "fill" | "fit" | "manual"
    x_offset: int = 960    # horizontal crop anchor in source pixels
    crop_preset: str = None  # "GAMING_STACKED_FIT" | None
    keypoints: list = []   # [[rel_t_s, x_offset_px], ...] for animated panning

    # Captions
    caption_enabled: bool = True
    caption_words: list = []  # word-level dicts from pipeline transcript
    caption_settings: dict = {}

    # Export
    codec: str = "h264"
    crf: int = 18
    render_engine: str = "ffmpeg"  # "ffmpeg" | "concat"
    edit_method: str = "pipeline_auto"
```

---

## Composition Modes

### 1. Fill (default)

For landscape 16:9 → portrait 9:16:
- `frameClip("fill")` scales source to fill canvas (scale ≈ 3.16 for 1920×1080→1080×1920)
- Source sides are cropped; no black bars
- `offsetX` shifts the crop window horizontally to center on subject

**Used by:** standard conversation, reaction, and dynamic clips.

### 2. Gaming Stacked FIT (`crop_preset="GAMING_STACKED_FIT"`)

Two-track composition showing gameplay and webcam in distinct zones:
- **Top track:** gameplay footage (full-width, fit mode, blurred background)
- **Bottom track:** webcam overlay (full-width, fit or fill based on ratio)
- Split ratios supported: 50/50, 60/40, 65/35, 70/30

See `GAMING_STACKED_TESTS.md` for implementation details.

### 3. Face Focus (planned)

Face-tracked reframing using person bounding box keyframes from the visual analyzer:
- Multiple `setClipKey` operations create keyframe animation
- Smooth panning follows detected face across the clip
- Activated via `keypoints` list with relative timestamps

---

## ConcatRenderRequest (Concat translation)

`EditPlan.to_concat_request()` produces a `ConcatRenderRequest`:

```python
@dataclass
class ConcatRenderRequest:
    source_path: str
    output_path: str
    start_s: float
    duration_s: float
    x_offset: int          # crop center in source px
    src_w: int = 1920
    src_h: int = 1080
    canvas_w: int = 1080
    canvas_h: int = 1920
    fps: int = 30
    keypoints: list = []   # for animated offsetX keyframes
    caption_words: list = []
    crf: int = 18
    codec: str = "h264"
```

---

## Adapter Phase Flow

```
Phase 1  project.create + media.import + project.save
         → get media_id, media_dur, track_id

Phase 2a project.open + addClip + project.save
         → get clip_id (from createdId, not hardcoded)

Phase 2b project.open + trimClip(head) + trimClip(tail) + frameClip("fill")
         + [setClipTransform(offsetX)] + [setClipKey keyframes] + [addTextClip captions]
         + project.save + export.run
         → output file
```

---

## offsetX Formula

For converting pipeline `x_offset` (left edge of 9:16 crop window in source pixels) to Concat `offsetX` (canvas width fractions):

```python
scale = canvas_h / src_h          # = 1.7778 for 1080p→1920
crop_w = src_h * canvas_w / canvas_h  # = 607px source pixels visible
center_x = (src_w - crop_w) // 2   # = 656 (default center window left edge)
shift_source_px = center_x - x_offset
offsetX = (shift_source_px * scale) / canvas_w
# Clamped to ±3.0 (Concat API limit)
```

Positive `offsetX` = clip moves right = more left-side source content visible.
