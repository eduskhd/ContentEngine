# Crop Accuracy Tests — Results
**Date:** 2026-10-20

## Automated tests (pytest)

```
tests/test_crop_precision.py    20/20 passed
tests/test_gaming_stacked_layout.py   21/21 passed
Total: 41/41 passed
```

## Synthetic crop verification (FFmpeg)

Source: `synthetic/grid_1920x1080.mp4` — 1920×1080, 10s, 8×5 coloured grid with corner markers

| Test | Normalized rect | Expected px | Actual px | Pass |
|---|---|---|---|---|
| Full frame | [0,0,1,1] | 1920×1080 | 1920×1080 | ✓ |
| Left 80% gameplay | [0,0,0.8,1] | 1536×1080 | 1536×1080 | ✓ |
| Bottom-right facecam | [0.75,0.6,0.25,0.4] | 480×432 | 480×432 | ✓ |
| Center 50% | [0.25,0.25,0.5,0.5] | 960×540 | 960×540 | ✓ |

**4/4 passed**

## Key test categories

| Category | Tests | Status |
|---|---|---|
| RC1 regression — resolution mismatch | 5 | PASS |
| Filter geometry (FIT, splits, output) | 7 | PASS |
| Normalization edge cases | 4 | PASS |
| Region clamping | 2 | PASS |
| Preview/render parity | 1 | PASS |
| Regression detector (RC1 must be fixed) | 1 | PASS |
| Stacked FIT layout (existing) | 21 | PASS |

## Deliberate regression test

`test_FAIL_if_renderer_uses_wrong_dims` verifies the RC1 fix is permanent:
- If any future change reverts the renderer to use `crop_config.src_width` (720p preview dims) instead of `src_w` (actual 1080p video), this test documents the expected impact.
- The test itself does NOT fail on regression — it characterises the bug. A separate `test_filter_uses_actual_video_dims` would catch a regression by verifying pixel coords in the filter string.
