"""Convert Content Engine framing data → Concat crop + transform parameters.

Content Engine stores framing as ``x_offset`` (horizontal center of the subject
in source pixel coordinates) from YOLOX person detection.  Concat uses a
different model: the project canvas is already set to the target resolution
(1080×1920) and clips are placed with ``framing="fill"``, which scales the
landscape source to fill the portrait canvas and crops the sides symmetrically.
The horizontal position is then adjusted via ``clip_transform.offsetX``, which
is expressed in *frame fractions* (1.0 = one full canvas width = 1080 px).

Derivation (for a 1920×1080 source → 1080×1920 canvas):
  - scale_factor = canvas_h / src_h = 1920 / 1080 = 1.778
  - scaled_src_w = src_w * scale_factor = 1920 * 1.778 = 3413 px
  - default_center_x_in_scaled = scaled_src_w / 2 = 1706 px
  - subject_x_in_scaled = x_offset * scale_factor
  - pixel_shift = subject_x_in_scaled - canvas_w / 2 - (default_center_x_in_scaled - canvas_w / 2)
               = (x_offset * scale_factor) - default_center_x_in_scaled
  - offset_x_fraction = -pixel_shift / canvas_w
    (negative because moving subject right = shifting clip left in canvas terms)

NOTE: The sign convention and exact behavior of ``offsetX`` must be validated
experimentally during Phase 6. The formula above is derived from the documented
API but has NOT been calibrated against real Concat output yet.
"""
from __future__ import annotations


def x_offset_to_concat_transform(
    x_offset: int,
    src_w: int = 1920,
    src_h: int = 1080,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> dict:
    """Return a ``clip_transform`` dict for Concat given the pipeline x_offset.

    x_offset is the LEFT EDGE of the 9:16 crop window in source pixels
    (same meaning as the x parameter in FFmpeg's crop=w:h:x:y filter).

    frameClip("fill") centers the source by default, showing:
      [center_x, center_x + crop_w] of the source, where
      center_x = (src_w - crop_w) // 2

    offsetX shifts the clip horizontally in canvas fractions:
      positive = clip moves right (canvas shows more of the left side of source)
      negative = clip moves left  (canvas shows more of the right side of source)

    To show [x_offset, x_offset + crop_w] instead of the default center window:
      shift_source_px = center_x - x_offset
      shift_scaled_px = shift_source_px * scale
      offsetX         = shift_scaled_px / canvas_w
    """
    scale = canvas_h / src_h
    crop_w = int(src_h * canvas_w / canvas_h)  # source pixels that fill the canvas width
    center_x = (src_w - crop_w) // 2           # default center-crop left edge
    shift_source_px = center_x - x_offset       # >0 = move clip right
    shift_scaled_px = shift_source_px * scale
    offset_x = shift_scaled_px / canvas_w
    # Clamp to ±3 (Concat documented limit)
    offset_x = max(-3.0, min(3.0, offset_x))
    return {
        "scale": 1.0,
        "offsetX": round(offset_x, 4),
        "offsetY": 0.0,
        "rotation": 0.0,
    }


def keypoints_to_concat_transforms(
    keypoints: list[list],
    duration_s: float,
    src_w: int = 1920,
    src_h: int = 1080,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> list[dict]:
    """Convert pipeline keypoints to a list of Concat keyframe dicts.

    Each keypoint is [rel_time_s, x_offset].  Returns a list of dicts:
    ``[{"time": t, "offsetX": f}, ...]`` suitable for ``keyframe_set`` calls.
    """
    result = []
    for kp in keypoints:
        if len(kp) < 2:
            continue
        rel_t, x_off = float(kp[0]), int(kp[1])
        transform = x_offset_to_concat_transform(x_off, src_w, src_h, canvas_w, canvas_h)
        result.append({"time": rel_t, "offsetX": transform["offsetX"]})
    return result
