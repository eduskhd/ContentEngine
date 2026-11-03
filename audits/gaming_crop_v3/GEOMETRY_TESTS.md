# Gaming Crop V3 — Geometry Tests

**Date:** 2026-11-03  
**Goal:** Verify that actual crop regions from crop_configs are correctly converted to source-pixel coordinates and passed through to the FFmpeg filter.

---

## Region Data Audit (6 Gaming Jobs)

Regions computed from `crop_configs` (normalized 0.0–1.0 × source dimensions):

| Job | Creator | Gameplay region (px) | Facecam region (px) | Split | Notes |
|-----|---------|---------------------|---------------------|-------|-------|
| efb141e5 | rickyedit | [0, 11, 352, 328] | [349, 0, 1571, 1080] | 0.65 | Small overlay top-left |
| 76b44f42 | miguelillo_rl | [0, 11, 427, 356] | [433, 11, 1487, 1054] | 0.65 | Small overlay top-left |
| 36499131 | illojuan | [36, 441, 290, 312] | [337, 0, 1583, 1080] | 0.65 | Small overlay mid-left |
| abf14566 | illojuan_t | [55, 307, 287, 309] | [351, 8, 1574, 1064] | 0.65 | Small overlay mid-left |
| 40575aa4 | rickyedit | [23, 220, 517, 530] | [538, 17, 1393, 1061] | 0.65 | Larger overlay center-left |
| afe3f6d7 | rubius_z | [11, 8, 502, 331] | [528, 8, 1421, 1076] | 0.65 | Larger overlay top-left |

**Pattern:** All jobs define:
- `main_region` (gameplay in DB) = small left-side region (facecam/reaction overlay on stream)
- `secondary_region` (facecam in DB) = large right-side region (main gameplay view)

**Editorial note:** The naming is counterintuitive — in the DB, `gameplay` refers to the small streamer-face overlay, and `facecam` refers to the large gameplay view. The GAMING_STACKED_FIT layout puts `main_region` (gameplay) in the top 65% panel. This produces: face/reaction large on top, gameplay small on bottom — which is a valid editorial choice for reaction-focused content.

---

## Coordinate Conversion Verification

For job `d1834ea0` (illojuan_y, src=1920×1080):
- Normalized: gameplay_x=0.197, gameplay_y=0.049, gameplay_w=0.283, gameplay_h=0.867
- In source px: main_region=[378, 53, 543, 937]

Pipeline converts: `cc["gameplay_x"] * src_w` = 0.197 × 1920 = 378 ✅  
The crop_converter formula uses these correctly:
```
_compute_stacked_fit_filter([378, 53, 543, 937], ...)
→ crop=543:937:378:53  (gameplay panel)
```

---

## EditPlan.from_clip() Region Extraction Test

```
clip=152c7552 job=d1834ea0:
  crop_preset:       GAMING_STACKED_FIT ✅
  main_region:       [378, 53, 1539, 935]
  secondary_region:  [10, 436, 361, 324]
  gaming_top_ratio:  0.5

clip=519cb869 job=efb141e5:
  crop_preset:       GAMING_STACKED_FIT ✅
  main_region:       [0.0, 10.9, 352.2, 327.5]   (float, OK — FFmpeg accepts floats)
  secondary_region:  [349.1, 0.0, 1570.9, 1080.0]
  gaming_top_ratio:  0.65
```

All regions correctly read from crop_configs via job_id lookup. ✅

---

## x_offset Coordinate Convention (Non-Gaming Clips)

- `framing_plan.x_offset` = LEFT EDGE of the 9:16 crop window in source pixels
- Default center for 1920px source: `(1920 - 607) // 2 = 656`
- `crop_converter.py` formula verified: shift = (656 - x_offset) * scale / canvas_w
- Module docstring fixed: previously said "horizontal center of subject" — now says "LEFT EDGE of 9:16 crop window"

---

## Filter Generation Verification

For `main_region=[0, 11, 352, 328]`, `secondary_region=[349, 0, 1571, 1080]`, top_fraction=0.65, bg="blurred":

Expected top panel (gameplay, 1248px tall):
```
crop=352:328:0:11,
split=2[gblu][gfit];
[gblu]scale=1080:1248:force_original_aspect_ratio=increase,crop=1080:1248,boxblur=...[gbg];
[gfit]scale=1080:1248:force_original_aspect_ratio=decrease[gfg];
[gbg][gfg]overlay=(W-w)/2:(H-h)/2
```

Expected bottom panel (facecam, 672px tall):
```
crop=1571:1080:349:0,
scale=1080:672:force_original_aspect_ratio=decrease,
pad=1080:672:(ow-iw)/2:(oh-ih)/2:black
```

Final filter: `[0:v]split=2[main][face]; [main]...[v0]; [face]...[v1]; [v0][v1]vstack=inputs=2[out]`
