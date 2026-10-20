# Preview–Render Parity Audit — Gaming Stacked Compositor

**Date:** 2026-10-20

---

## Problem

If the preview shown in New Job uses different compositor code than the final render, the user can't trust what they see in the preview. This was flagged as a critical issue to verify.

---

## Code Path Comparison

### Preview endpoint (`POST /crop-configs/preview-file`)

```python
from engine.renderers.render_clip import _compute_stacked_fit_filter as _csf
main_region = [gp[0] * src_width, gp[1] * src_height, gp[2] * src_width, gp[3] * src_height]
sec_region  = [fc[0] * src_width, fc[1] * src_height, fc[2] * src_width, fc[3] * src_height]
filt = _csf(main_region, sec_region, src_width, src_height, top_fraction=split_fraction, bg=gameplay_bg)
```

### Final render (`engine/renderers/render_clip.py:_render_one`)

```python
split_layout_filter = _compute_stacked_fit_filter(
    framing_plan["main_region"],
    framing_plan["secondary_region"],
    src_w, src_h,
    top_fraction=top_frac,
    bg=gbg,
)
```

**Both use `_compute_stacked_fit_filter` from the same module.**

The ONLY difference is the input resolution used for denormalization:
- Preview: uses `src_width/src_height` from the form upload (which is the actual file's resolution)
- Final render: uses `src_w/src_h` from ffprobe on the downloaded file

For URL sources: preview uses `src_width` from the URL preview endpoint (which extracts a frame at that resolution). The final render uses the actual downloaded resolution.

---

## Parity Issue for URL Sources (Known Limitation)

For URL-sourced videos:
- Preview frame extracted at 720p → `src_width=1280, src_height=720`
- Final download at 1080p → `src_w=1920, src_h=1080`

The preview compositor filter uses `1280×720` to denormalize; the final render uses `1920×1080`. The NORMALIZED coords are the same — they're stored in [0-1] — but the panel sizes differ slightly:
- Preview: `TOP_H = 1248px` in a 1280-wide panel
- Final: `TOP_H = 1248px` in a 1080-wide (TARGET_W) output

Wait — both compute `top_h = int(TARGET_H * split_fraction)` which is RESOLUTION-INDEPENDENT. The `split_fraction` and `TARGET_H` are the same in both paths. The only difference is the crop region source coordinates.

**Conclusion:** For the OUTPUT dimensions (1080×1920, panel heights), preview and render are IDENTICAL. For the exact pixel content of each panel, there is a cosmetic 1.5× resolution difference for 720p-preview / 1080p-render pairs, but the layout structure is identical.

---

## Test Coverage

```
tests/test_crop_precision.py::TestPreviewRenderParity
  test_same_normalized_coords_produce_proportional_filter   PASS
```

This test verifies that the same normalized coordinates produce proportional (correct) crop filters regardless of whether the source resolution is 720p or 1080p.

---

## URL Preview Endpoint Parity (`POST /crop-configs/preview-url`)

Same function call: `_csf_url` delegates to `_compute_stacked_fit_filter`.

```python
filt = _csf_url(main_region, sec_region, src_w, src_h, top_fraction=split_fraction, bg=gameplay_bg)
```

Panel heights computed from `split_fraction` are identical to the final render.
