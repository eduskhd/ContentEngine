# Gaming Crop V3 — A/B Render Comparison

**Date:** 2026-11-03  
**Clips tested:** 3 (one per gaming job, diverse region configurations)

---

## Methodology

- **Variant A (broken):** `main_region=None, secondary_region=None` → adapter falls back to full source frame [0,0,src_w,src_h] for both panels
- **Variant B (fixed):** `main_region` and `secondary_region` from `crop_configs` table → adapter uses actual gameplay/facecam bounding boxes

Engine: `_render_gaming_stacked_via_ffmpeg` (FFmpeg, GAMING_STACKED_FIT preset, bg=blurred)

---

## Results

### Clip 01 — rickyedit (job=efb141e5)
- Duration: 36.6s | Split: 0.65 | Source: 1920×1080
- Gameplay region: [0, 11, 352, 328] (small top-left overlay)
- Facecam region: [349, 0, 1571, 1080] (large main view)

| Variant | Size | Render time | Output |
|---------|------|-------------|--------|
| A (broken, full-frame) | 20.4 MB | 37.7s | `clip_01_A_broken.mp4` |
| B (fixed, actual regions) | 26.3 MB | 33.9s | `clip_01_B_fixed.mp4` |

Visual difference:
- A: Both panels show the full 1920×1080 frame (letterboxed/squished)
- B: Top panel shows the 352×328 overlay (upscaled with blurred background), bottom panel shows the 1571×1080 main view (downscaled to fit)

---

### Clip 02 — miguelillo_rl (job=76b44f42)
- Duration: 33.3s | Split: 0.65 | Source: 1920×1080
- Gameplay region: [0, 11, 427, 356] (small top-left overlay)
- Facecam region: [433, 11, 1487, 1054] (large main view)

| Variant | Size | Render time | Output |
|---------|------|-------------|--------|
| A (broken, full-frame) | 40.9 MB | 27.7s | `clip_02_A_broken.mp4` |
| B (fixed, actual regions) | 28.8 MB | 26.0s | `clip_02_B_fixed.mp4` |

---

### Clip 03 — illojuan (job=36499131)
- Duration: 31.1s | Split: 0.65 | Source: 1920×1080
- Gameplay region: [36, 441, 290, 312] (small mid-left overlay)
- Facecam region: [337, 0, 1583, 1080] (large main view)

| Variant | Size | Render time | Output |
|---------|------|-------------|--------|
| A (broken, full-frame) | 5.9 MB | 30.2s | `clip_03_A_broken.mp4` |
| B (fixed, actual regions) | 7.6 MB | 28.9s | `clip_03_B_fixed.mp4` |

---

## Summary

| | A (broken) | B (fixed) |
|-|------------|-----------|
| Renders completed | 3/3 ✅ | 3/3 ✅ |
| Output size (avg) | 22.4 MB | 20.9 MB |
| Render time (avg) | 31.9s | 29.6s |
| Panel differentiation | ❌ Both panels identical | ✅ Each panel shows different region |
| Editorial quality | ❌ Viewer sees same content twice | ✅ Facecam/reaction + gameplay separated |

---

## Editorial Assessment

**Variant B is editorially correct.** Each panel shows a different region:
- Top 65%: Streamer's face/reaction overlay (small region, upscaled with blurred bg)
- Bottom 35%: Main gameplay + context (large region, downscaled to fit)

**Note on region labeling:** In all 10 gaming jobs, the user configured:
- `gameplay_rect` (→ `main_region`, top panel) = the small streamer-face overlay on the game screen
- `facecam_rect` (→ `secondary_region`, bottom panel) = the main gameplay view

This is a valid editorial choice for Spanish streaming content (reaction-focused), even though the naming in the DB (`gameplay` = small overlay, `facecam` = large gameplay view) is counterintuitive relative to the field names.

---

## Render Output Location

```
audits/gaming_crop_v3/renders/
├── clip_01_A_broken.mp4   20.4 MB
├── clip_01_B_fixed.mp4    26.3 MB
├── clip_02_A_broken.mp4   40.9 MB
├── clip_02_B_fixed.mp4    28.8 MB
├── clip_03_A_broken.mp4    5.9 MB
├── clip_03_B_fixed.mp4     7.6 MB
└── ab_results.json
```
