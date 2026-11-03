# Visual QA

**Status:** COMPLETE  
**Date:** 2026-11-03

---

## Methodology

12 frame captures extracted at t=5s from each render (4 creators × 3 variants).  
All frames stored in `evidence/` as PNG.  
Visual inspection performed on each frame.

---

## Pass/Fail Criteria

| Check | Pass Condition | Fail Condition |
|-------|---------------|----------------|
| Aspect ratio | 9:16 portrait, content fills canvas | Black bars top/bottom or left/right |
| Black bars | None visible | Any black padding visible |
| Content visibility | Subject (speaker/game) fills majority of frame | Subject occupies <50% of frame height |
| Crop accuracy | Subject centered or near-centered | Subject at extreme edge or cut off |

---

## Frame-by-Frame Results

### rubius_z

| Variant | File | Pass? | Notes |
|---------|------|-------|-------|
| A (FFmpeg) | `rubius_z_A_frame.png` | ✅ PASS | Face close-up, portrait fill. Speaker (open mouth, reaction) centered. No black bars. |
| B (Broken) | `rubius_z_B_frame.png` | ❌ FAIL | Massive black bars top (~32%) and bottom (~36%). Content (face + game) in narrow horizontal strip. Confirms pre-fix letterbox bug. |
| C (Fixed) | `rubius_z_C_frame.png` | ✅ PASS | Gaming inventory UI fills full canvas. Portrait orientation. No black bars. Correct fill-crop. |

### thegrefg

| Variant | File | Pass? | Notes |
|---------|------|-------|-------|
| A (FFmpeg) | `thegrefg_A_frame.png` | ✅ PASS | Portrait fill. "EVENTO DE FINAL DE CAPÍTULO" overlay, speaker top-right, game map bottom. Correct. |
| B (Broken) | `thegrefg_B_frame.png` | ❌ FAIL | Same letterbox pattern. Spanish text visible but content tiny (~34% of frame height). Black bars prominent. |
| C (Fixed) | `thegrefg_C_frame.png` | ✅ PASS | Full canvas fill. Same content as A. Text overlay readable at full width. No black bars. |

### illojuan

| Variant | File | Pass? | Notes |
|---------|------|-------|-------|
| A (FFmpeg) | `illojuan_A_frame.png` | ✅ PASS | Portrait fill. |
| B (Broken) | `illojuan_B_frame.png` | ❌ FAIL | Letterboxed. Black bars. |
| C (Fixed) | `illojuan_C_frame.png` | ✅ PASS | Portrait fill, no black bars. |

### iker_unzu

| Variant | File | Pass? | Notes |
|---------|------|-------|-------|
| A (FFmpeg) | `iker_unzu_A_frame.png` | ✅ PASS | Portrait fill. |
| B (Broken) | `iker_unzu_B_frame.png` | ❌ FAIL | Letterboxed. Black bars. |
| C (Fixed) | `iker_unzu_C_frame.png` | ✅ PASS | Portrait fill, no black bars. |

---

## Summary

| Variant | PASS | FAIL |
|---------|------|------|
| A (FFmpeg current) | 4/4 | 0/4 |
| B (Concat broken) | 0/4 | **4/4** |
| C (Concat fixed) | **4/4** | 0/4 |

**All 4 B frames confirm the letterbox bug** — each shows the same pattern of black padding with content in a narrow center strip.

**All 4 C frames pass** — full portrait fill with no black bars, matching the FFmpeg A output quality.

---

## Calibration Reference

Additional visual evidence from calibration tests:

| File | Description | Confirms |
|------|-------------|---------|
| `experiments/calib_fill_frame.png` | FrameClip("fill") on grid video | Fill mode works correctly, scale=3.1605 |
| `experiments/diag_both_fill_frame.png` | Two-track diagnostic (T1 calib + T2 red) | T2 renders on top of T1 (track order confirmed) |
| `experiments/stack_v2_frame.png` | Gaming Stacked Concat attempt | Zone boundaries incorrect → FFmpeg fallback justified |

---

## Conclusion

The Concat adapter fix (both bug 1 and bug 2) produces visually correct portrait fills across all 4 tested creators. The output is visually indistinguishable from the FFmpeg pipeline renders in terms of framing quality.
