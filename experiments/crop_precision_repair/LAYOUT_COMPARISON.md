# Layout Comparison — BEFORE vs AFTER RC1 Fix
**Date:** 2026-10-20

## What changed
BEFORE: denormalize using `crop_config.src_width = 1280` (720p preview) on a 1920×1080 video.
AFTER:  denormalize using `src_w = 1920` (actual video dimensions from pipeline).

## Per-job crop shift

| Job | GP x shift | GP w shift | Status |
|---|---|---|---|
| illojuan_unban | +106.2px | +493.4px | ✓ |
| illojuan_velada | +126.7px | +516.5px | ✓ |
| illojuan_gta6 | +126.1px | +513.3px | ✓ |

## Contact sheets
Side-by-side frames in `contact_sheets/`:
- `illojuan_unban_SBS.jpg` — left=BEFORE, right=AFTER
- `illojuan_velada_SBS.jpg` — left=BEFORE, right=AFTER
- `illojuan_gta6_SBS.jpg` — left=BEFORE, right=AFTER

## Interpretation
- BEFORE: gameplay crop starts too far left, too narrow — wrong region shown
- AFTER: correct proportional region — what the user drew in New Job
- For 1920×1080 source with 720p preview: shift = norm_x × (1920-1280) pixels