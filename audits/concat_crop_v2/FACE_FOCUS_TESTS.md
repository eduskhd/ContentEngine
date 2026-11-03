# Face Focus Tests

**Status:** PLANNED — not yet implemented in Concat adapter  
**Date:** 2026-11-03

---

## Objective

Implement face-tracked reframing using person bounding box keyframes from the visual analyzer. The Concat adapter should animate `offsetX` across the clip to follow the speaker's face position.

---

## Design

### Data Source

The visual analyzer (`engine/analyzers/visual_analyzer.py`) runs on the 360p proxy and reports face positions per-second:

```python
face_data = {
    "has_face": True,
    "face_center_x": 0.72,   # normalized 0-1 in source frame
    "face_center_y": 0.35,
    "face_size": 0.18
}
```

Currently only the dominant face per-clip is stored (averaged). For keyframe animation, we need per-second face positions.

### EditPlan keypoints field

`EditPlan.keypoints` is already defined:

```python
keypoints: list = field(default_factory=list)
# Format: [[rel_t_s, x_offset_px], ...]
# rel_t_s: time relative to clip start (0.0 = clip start)
# x_offset_px: horizontal crop anchor in source pixels
```

### offsetX formula (from COMPOSITION_MODEL.md)

```python
scale = canvas_h / src_h              # = 1.7778 for 1080→1920
crop_w_src = src_h * canvas_w / canvas_h  # = 607px of source visible
center_default = (src_w - crop_w_src) // 2  # = 656px (default left edge)
shift_px = center_default - x_offset_px
offsetX = (shift_px * scale) / canvas_w     # canvas width fractions
# Clamped to [-3.0, 3.0]
```

### Concat keyframe API

```python
{
    "op": "setClipKey",
    "clipId": clip_id,
    "prop": "offsetX",
    "time": rel_t_s,
    "value": offsetX_fraction
}
```

Multiple `setClipKey` calls create the animation curve. Concat interpolates between keyframes.

---

## Implementation Plan

### Step 1 — Extend visual analyzer

Currently `visual_analyzer.py` averages face positions. Need per-second samples stored in the candidate or clip row.

Proposed: Add `face_keypoints` to `candidates.score_breakdown` JSON:

```json
"face_keypoints": [[0.0, 0.52], [1.0, 0.58], [2.0, 0.61], ...]
```

where `[t_s, face_center_x_normalized]` pairs give face position per second.

### Step 2 — EditPlan constructor

In `EditPlan.from_clip()`, read `face_keypoints` from score breakdown and convert to `x_offset_px`:

```python
face_kps = score_breakdown.get("face_keypoints", [])
keypoints = [
    [t, int(face_cx * src_w)]   # face_center_x * src_w = source pixel position
    for t, face_cx in face_kps
]
```

### Step 3 — Adapter Phase 2b

In `adapter.py`, after frameClip, add setClipKey operations for each keypoint:

```python
for rel_t, x_offset_px in req.keypoints:
    scale = req.canvas_h / req.src_h
    crop_w_src = req.src_h * req.canvas_w / req.canvas_h
    center_default = (req.src_w - crop_w_src) / 2
    shift_px = center_default - x_offset_px
    offsetX = (shift_px * scale) / req.canvas_w
    offsetX = max(-3.0, min(3.0, offsetX))
    p2_reqs.append({...setClipKey offsetX...})
```

---

## Expected Behavior

| Scenario | Without keyframes | With keyframes |
|----------|------------------|----------------|
| Speaker centered | Correct | Same (no change needed) |
| Speaker left of center | Speaker cut off on right | Camera pans left to follow |
| Speaker moves during clip | Static crop, may miss action | Smooth pan tracks movement |
| Gaming clip (no face) | Centered crop | No keyframes added (graceful no-op) |

---

## Known Constraints

1. **Visual analyzer granularity:** Current proxy is 2fps → face samples every 0.5s. Keyframe animation at 2fps may produce visible steps. Smoothing or interpolation needed.
2. **offsetX clamping:** Concat API limits offsetX to ±3.0. For extreme off-center subjects this may be insufficient.
3. **Multi-face clips:** Concat adapter currently tracks only one subject. Multi-face clips (interview format) would require subject selection logic.
4. **Performance:** Each keyframe = one `setClipKey` API call batched into Phase 2b. A 30s clip at 2fps = 60 calls — well within Concat's batch limit.

---

## Status

Not yet implemented. The infrastructure is in place:
- `EditPlan.keypoints` field exists ✅
- `to_concat_request()` passes keypoints ✅
- Adapter has placeholder logic for keypoint operations ✅
- Visual analyzer does not yet emit per-second face positions ❌
- No integration test ❌

**Blocked by:** visual analyzer per-second face keypoint export.

This is a Phase 3 feature. Current V2 scope (fill crop correctness) is complete.
