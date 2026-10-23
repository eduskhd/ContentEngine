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

    Args:
        x_offset: horizontal center of subject in source pixels (from framing_plan)
        src_w, src_h: source video dimensions
        canvas_w, canvas_h: Concat project canvas (target output resolution)

    Returns:
        dict suitable for the ``arguments`` of ``clip_transform`` MCP call:
        ``{"scale": 1.0, "offsetX": <fraction>, "offsetY": 0.0, "rotation": 0.0}``
    """
    scale = canvas_h / src_h
    scaled_src_w = src_w * scale
    default_center = scaled_src_w / 2.0
    subject_center = x_offset * scale
    # Shift needed in scaled pixels to center subject in canvas
    pixel_shift = subject_center - canvas_w / 2.0 - (default_center - canvas_w / 2.0)
    # Concat offsetX: positive = move clip right; negative = move clip left
    # To bring subject from right-of-center to canvas center, shift clip left (negative)
    offset_x = -pixel_shift / canvas_w
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
