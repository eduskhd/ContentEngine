# Test Results — Gaming Stacked Compositor Fix

**Date:** 2026-10-20  
**Run:** Full test suite

---

## Gaming Stacked Layout (21/21)

```
tests/test_gaming_stacked_layout.py

test_default_split_65_35                     PASS
test_split_50_50                             PASS
test_split_60_40                             PASS
test_split_70_30                             PASS
test_top_plus_bot_equals_total[0.5]          PASS
test_top_plus_bot_equals_total[0.6]          PASS
test_top_plus_bot_equals_total[0.65]         PASS
test_top_plus_bot_equals_total[0.7]          PASS
test_gameplay_uses_fit_not_fill              PASS
test_no_gameplay_crop_after_scale            PASS
test_facecam_uses_fit_pad                    PASS
test_vstack_output                           PASS
test_output_label_out                        PASS
test_blurred_bg_uses_boxblur                 PASS
test_blurred_bg_uses_overlay_not_pad_for_gameplay  PASS
test_blurred_bg_facecam_still_padded         PASS
test_blurred_bg_has_increase_and_decrease    PASS
test_region_clamping                         PASS
test_output_width_is_target_w               PASS
test_stacked_fit_differs_from_manual_split   PASS
test_caption_safe_zone_calculation           PASS

Result: 21 PASSED
```

---

## Crop Precision (20/20)

```
tests/test_crop_precision.py

TestRC1ResolutionMismatch::test_same_ar_different_res_produces_proportional_region  PASS
TestRC1ResolutionMismatch::test_1080p_pixel_coords_are_1_5x_720p_for_16_9          PASS
TestRC1ResolutionMismatch::test_wrong_resolution_causes_crop_shift                  PASS
TestRC1ResolutionMismatch::test_norm_coords_roundtrip_1920x1080                    PASS
TestRC1ResolutionMismatch::test_filter_uses_actual_video_dims                      PASS
TestFilterGeometry::test_filter_contains_correct_gameplay_crop_width               PASS
TestFilterGeometry::test_output_width_target_w                                     PASS
TestFilterGeometry::test_vstack_output                                             PASS
TestFilterGeometry::test_no_force_increase_in_black_mode                          PASS
TestFilterGeometry::test_fit_decrease_present                                      PASS
TestFilterGeometry::test_split_65_35_top_height                                   PASS
TestFilterGeometry::test_split_fractions_sum_to_target_h                          PASS
TestNormalizationEdgeCases::test_zero_origin_full_frame                           PASS
TestNormalizationEdgeCases::test_bottom_right_quadrant                            PASS
TestNormalizationEdgeCases::test_tiny_region_not_zero                             PASS
TestNormalizationEdgeCases::test_rounding_even_codec_constraint                   PASS
TestRegionClamping::test_out_of_bounds_clamped                                    PASS
TestRegionClamping::test_zero_width_region_gets_minimum                           PASS
TestPreviewRenderParity::test_same_normalized_coords_produce_proportional_filter  PASS
TestRegressionDetector::test_FAIL_if_renderer_uses_wrong_dims                    PASS

Result: 20 PASSED
```

---

## Full Suite Regression Check

```
374 passed / 12 failed / 386 total
```

Pre-existing failures (NOT caused by gaming fix):
- test_packages_batches (5): creator_slug column missing in test DB
- test_publish_queue::test_claim_is_exclusive_concurrent (1): intermittent DB lock
- test_reframing_v12 (3): pre-existing smart reframing thresholds
- test_reframing_v12_repair (1): pre-existing
- test_yt_publishing (2): pre-existing OAuth/DB lock

**No new regressions introduced by the gaming stacked compositor fix.**

---

## FFmpeg Synthetic Tests (from crop_precision_repair/synthetic/)

4 tests run via `verify_crop_accuracy.py` on a synthetic grid video (1920×1080):
- `center_50pct.mp4` — center crop correct
- `gameplay_80pct.mp4` — 80% width gameplay crop correct  
- `facecam_br.mp4` — bottom-right quadrant facecam crop correct
- `full_frame.mp4` — full frame passthrough correct

All 4 verified pixel-accurate.

---

## Integration Tests (3 IlloJuan Gaming Jobs)

Job | Resolution | Clips | QA | Path Exists
----|-----------|-------|-----|------------
c6fa6cf9 (GTA6) | 1280×720 | 5 | 5×PASS 1080×1920 | ✓
179734c2 (Unban) | 1280×720 | 5 | 5×PASS 1080×1920 | ✓
d1834ea0 (Velada) | 1280×720 | 5 | 5×PASS 1080×1920 | ✓
