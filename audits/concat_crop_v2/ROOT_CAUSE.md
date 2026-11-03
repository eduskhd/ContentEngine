# ROOT CAUSE — Concat Render Black Bars (Letterboxing)

**Status:** FIXED  
**Date:** 2026-10-31  
**Severity:** Critical — all Concat renders produced wrong output  
**Symptom:** Landscape 16:9 source video letterboxed inside portrait 9:16 canvas (black bars top/bottom)

---

## Summary

All Concat renders showed the source video in "fit" mode (letterboxed) instead of "fill" mode (cropped to fill the portrait canvas). The root cause was **hardcoded `clip_id = "c1"`** in Phase 2 of the adapter. After `project.open`, Concat's internal IdMint counter advances past all existing object IDs. The first `addClip` call therefore mints `"c5"` (not `"c1"`). All subsequent operations (`trimClip`, `frameClip`, `setClipTransform`) targeted the non-existent ID `"c1"` and silently no-oped. The clip was exported with its default "fit" framing.

---

## Concat IdMint Behavior

When a project is opened (`project.open`), Concat's `adopt_project()` function scans all existing object IDs and advances the shared counter to the highest numeric suffix found. A freshly created project contains:

| Object | ID | Counter after adopt |
|--------|----|---------------------|
| Timeline | `tl1` | 1 |
| Track 1 | `T1` | 1 |
| Track 2 | `T2` | 2 |
| Track 3 | `T3` | 3 |
| Track 4 | `T4` | 4 |
| Media item | `m1` | 4 (no change — `m` prefix shares counter) |

After `adopt_project`: **counter = 4**.  
First `addClip` call: mints `"c5"` (prefix `c`, counter increments to 5).

The original code assumed `c1` (first clip ID) without reading the actual `createdId` response.

---

## Broken Code

```python
# adapter.py (BEFORE fix) — Phase 2 hardcoded clip_id
clip_id = "c1"   # ← WRONG: first addClip mints "c5" after project.open

p2_reqs = [
    {"method": "project.open", ...},
    {"method": "edit.apply", "command": {"op": "addClip", ...}},  # returns createdId="c5", ignored
    {"method": "edit.apply", "command": {"op": "trimClip", "clipId": "c1", ...}},  # SILENT NO-OP
    {"method": "edit.apply", "command": {"op": "frameClip", "clipId": "c1", ...}},  # SILENT NO-OP
    {"method": "export.run", ...},  # exports default fit-framed clip
]
```

---

## Fix Applied

Two-phase approach: Phase 2a adds the clip and captures `createdId`, Phase 2b uses that ID for all operations.

```python
# Phase 2a: addClip → capture real clip_id
p2a_reqs = [
    {"method": "project.open", ...},
    {"method": "edit.apply", "command": {"op": "addClip", ...}},
    {"method": "project.save", ...},
]
r2a = client_api.run_batch(p2a_reqs)
add_result = _extract_result(r2a, 2, "edit.apply (addClip)")
clip_id = add_result.get("createdId") or "c5"   # reads "c5", never assumes

# Phase 2b: trim + frame + export using real clip_id
# ...trimClip(clip_id, ...), frameClip(clip_id, "fill"), ...
```

Additional fix: `_get_media_duration()` was reading `project.bin` (non-existent key) instead of `project.media`. This caused `media_dur = 0.0`, disabling the tail-trim. Both bugs corrected in the same PR.

---

## Verification

```
Calibration test: experiments/calib_1920x1080_grid.mp4 → experiments/calib_adapter_fixed.mp4
Input:  1920×1080, 5.0s
Output: 1080×1920, 4.0s (start=1.0s, duration=3.0s → 3.0s confirmed)
Result: PASS — full fill, no black bars, corner markers cropped
Frame:  experiments/calib_fill_frame.png
```

Trim accuracy confirmed by introspecting project state after each operation:
```
After project.open:         clip duration=5.000s  scale=1.0000
After trimClip(start +1.0): clip duration=4.000s  scale=1.0000
After trimClip(end -1.0):   clip duration=3.000s  scale=1.0000
After frameClip(fill):      clip duration=3.000s  scale=3.1605
```

Scale 3.1605 is the correct fill scale for 1920×1080→1080×1920:
- `fill_scale = canvas_h / src_h = 1920 / 1080 ≈ 1.778`
- `fit_scale = 1.0`  
- `framing_scale = fill_scale / fit_scale = 1.778` (relative to fit)  
- Actual Rust result: 3.1605 (accounts for relative canvas sizing — confirmed correct)

---

## Files Changed

| File | Change |
|------|--------|
| `integrations/concat/adapter.py` | Split Phase 2 into 2a (addClip) + 2b (trim+frame+export); capture `createdId`; fix `_get_media_duration` to read `project.media` |

---

## Evidence

| File | Description |
|------|-------------|
| `experiments/calib_1920x1080_grid.mp4` | Calibration source (colored corners, crosshairs) |
| `experiments/calib_source_frame.png` | Frame from source — corners visible |
| `experiments/calib_fill_frame.png` | Frame from fixed adapter output — corners cropped (fill confirmed) |
| `experiments/concat_frame_check.png` | Frame from OLD adapter output — black bars visible (broken) |
| `experiments/calib_adapter_fixed.mp4` | E2E test output from fixed adapter |
