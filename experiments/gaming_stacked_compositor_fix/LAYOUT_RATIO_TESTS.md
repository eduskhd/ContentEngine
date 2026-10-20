# Layout Ratio Tests — Gaming Stacked Compositor

**Date:** 2026-10-20  
**Source:** IlloJuan gaming clip (illowanillo_8zup_jkbdwa.mp4) — 1280×720  
**Renders:** `experiments/gaming_stacked_layout/`

---

## Render Evidence

All 6 renders are 1080×1920, ~8 seconds, confirmed by ffprobe.

| File | Mode | Split | TOP_H | BOT_H | Status |
|------|------|-------|-------|-------|--------|
| `00_current_fill_65_35.mp4` | v11 FILL (old) | 65/35 | 1248 | 672 | BASELINE |
| `01_stacked_fit_50_50.mp4` | GAMING_STACKED_FIT | 50/50 | 960 | 960 | ✓ PASS |
| `02_stacked_fit_60_40.mp4` | GAMING_STACKED_FIT | 60/40 | 1152 | 768 | ✓ PASS |
| `03_stacked_fit_65_35.mp4` | GAMING_STACKED_FIT | 65/35 | 1248 | 672 | ✓ PASS |
| `04_stacked_fit_70_30.mp4` | GAMING_STACKED_FIT | 70/30 | 1344 | 576 | ✓ PASS |
| `05_stacked_fit_65_35_blurred.mp4` | GAMING_STACKED_FIT | 65/35 | 1248 | 672 | ✓ PASS |

---

## Unit Test Coverage

```
tests/test_gaming_stacked_layout.py — 21 tests

test_default_split_65_35         → top_h=1248, bot_h=672
test_split_50_50                 → top_h=960,  bot_h=960
test_split_60_40                 → top_h=1152, bot_h=768
test_split_70_30                 → top_h=1344, bot_h=576
test_top_plus_bot_equals_total   → sum=1920 for all 4 ratios
test_gameplay_uses_fit_not_fill  → force_original_aspect_ratio=decrease present
test_no_gameplay_crop_after_scale → no second crop= after scale (FIT not FILL)
test_facecam_uses_fit_pad        → facecam uses decrease+pad
test_vstack_output               → vstack=inputs=2 present
test_output_label_out            → [out] label present for filter_complex routing
test_blurred_bg_uses_boxblur     → boxblur present in blurred variant
test_blurred_bg_uses_overlay_not_pad_for_gameplay → overlay not pad for bg=blurred
test_blurred_bg_facecam_still_padded → facecam still uses FIT+pad in blurred variant
test_blurred_bg_has_increase_and_decrease → blurred has both scale modes
test_region_clamping             → out-of-bounds regions clamped to valid range
test_output_width_is_target_w    → TARGET_W=1080 in all scale calls
test_stacked_fit_differs_from_manual_split → new function distinct from old
test_caption_safe_zone_calculation → margin_v = TARGET_H - top_h + 100
```

All 21 PASS.

---

## Verification vs Spec Requirements

| Spec Requirement | Status |
|-----------------|--------|
| 50/50: gameplay=960px, webcam=960px | ✓ |
| 60/40: gameplay=1152px, webcam=768px | ✓ |
| 65/35: gameplay=1248px, webcam=672px | ✓ |
| 70/30: gameplay=1344px, webcam=576px | ✓ |
| Sum always 1920 | ✓ |
| Gameplay starts at y=0 | ✓ (vstack: v0 top) |
| Webcam starts where gameplay ends | ✓ (vstack: v1 bottom) |
| No gap, no overlap | ✓ (sum=1920, vstack) |
| FIT preserves all gameplay content | ✓ (decrease+pad) |
| No distortion | ✓ (force_original_aspect_ratio=decrease) |
