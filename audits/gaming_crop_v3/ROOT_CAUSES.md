# Gaming Crop V3 — Root Causes

**Date:** 2026-11-03  
**Status:** All 5 root causes fixed in this session.

---

## Bug 1 — `_render_gaming_stacked_via_ffmpeg` used full-frame for both panels (CRITICAL)

**File:** `integrations/concat/adapter.py` lines 407–410 (before fix)  
**Severity:** CRITICAL — both panels showed identical full-frame content

**Root cause:** `main_region` and `secondary_region` were hardcoded to `[0, 0, src_w, src_h]` (full source frame). The actual gameplay and facecam bounding boxes from `crop_configs` were never propagated to the Concat path.

**Before:**
```python
main_region     = [0, 0, src_w, src_h]   # top: full frame
secondary_region = [0, 0, src_w, src_h]  # bottom: full frame
```

**After:**
```python
if req.main_region and req.secondary_region:
    main_region = req.main_region
    secondary_region = req.secondary_region
else:
    # Full-frame fallback — no region data available
    main_region = [0, 0, src_w, src_h]
    secondary_region = [0, 0, src_w, src_h]
```

---

## Bug 2 — `ConcatRenderRequest` had no fields for gaming regions (CRITICAL)

**File:** `integrations/concat/adapter.py` `ConcatRenderRequest` dataclass  
**Severity:** CRITICAL — even if callers had region data, there was no way to pass it

**Root cause:** `ConcatRenderRequest` lacked `main_region` and `secondary_region` fields. The only gaming-related fields were `crop_preset` (to trigger the FFmpeg fallback) and `gaming_top_ratio` (split fraction).

**Fix:** Added optional `main_region: Optional[list] = None` and `secondary_region: Optional[list] = None` fields to `ConcatRenderRequest`.

---

## Bug 3 — `EditPlan.from_clip()` ignored `crop_configs` table (CRITICAL)

**File:** `integrations/concat/edit_plan.py` `from_clip()` method  
**Severity:** CRITICAL — gaming layout data (gameplay/facecam bounding boxes) lives in `crop_configs` keyed by `job_id`, but `from_clip()` only read `framing_plan` from the candidates table

**Root cause:** `from_clip()` queried `candidates.framing_plan` which stores v2 `face_center_static` data — never split_layout gaming data. Gaming clips use `crop_configs.gameplay_x/y/w/h` and `crop_configs.facecam_x/y/w/h` (normalized 0.0–1.0 coordinates).

**Fix:** After reading `framing_plan`, `from_clip()` now:
1. Gets `job_id` from the clip row
2. Calls `get_crop_config(job_id)`
3. If `gameplay_x` is set: computes `main_region` and `secondary_region` (scaled to source pixels)
4. Sets `crop_preset` from `layout_preset` column (default: `GAMING_STACKED_FIT`)
5. Sets `gaming_top_ratio` from `split_fraction` column (default: 0.65)

---

## Bug 4 — `EditPlan` had no gaming region fields (MEDIUM)

**File:** `integrations/concat/edit_plan.py` `EditPlan` dataclass  
**Severity:** MEDIUM — `EditPlan` is the data contract between pipeline and Concat; missing fields made region data impossible to serialize/carry

**Fix:** Added three new fields:
```python
main_region: Optional[list] = None
secondary_region: Optional[list] = None
gaming_top_ratio: float = 0.65
```

Also updated `to_concat_request()` to pass all three to `ConcatRenderRequest`.

---

## Bug 5 — `detect_encoder()` returns 3 values but adapter unpacked 2 (RUNTIME ERROR)

**File:** `integrations/concat/adapter.py` `_render_gaming_stacked_via_ffmpeg()` line 429  
**Severity:** HIGH — caused ALL gaming stacked renders to fail with `ValueError: too many values to unpack`

**Root cause:** `detect_encoder()` returns `(encoder, enc_opts, tier)` (3-tuple) but the adapter had:
```python
encoder, enc_opts = detect_encoder()  # ValueError: too many values to unpack
```

**Fix:**
```python
encoder, enc_opts, _tier = detect_encoder()
```

---

## Bug 6 — `crop_converter.py` module docstring wrong description of x_offset (DOCUMENTATION)

**File:** `integrations/concat/crop_converter.py` module docstring  
**Severity:** LOW — documentation only, no runtime impact

**Root cause:** Line 3 said "x_offset (horizontal center of the subject in source pixel coordinates)" which was incorrect. The `x_offset` is the LEFT EDGE of the 9:16 crop window, identical to FFmpeg's `crop=w:h:x:y` `x` parameter.

**Fix:** Updated module docstring to say "the LEFT EDGE of the 9:16 crop window in source pixels".

---

---

## Bug 7 — `_render_gaming_stacked_via_ffmpeg` used `-vf` with a `filter_complex` graph (RUNTIME ERROR)

**File:** `integrations/concat/adapter.py` lines 427–443 (before fix)  
**Severity:** HIGH — caused ALL gaming stacked renders to fail with `Error linking filters`

**Root cause:** `_compute_stacked_fit_filter` returns a complete `filter_complex` graph ending in `[out]`:
```
[0:v]split=2[main][face];[main]...;[face]...;[v0][v1]vstack=inputs=2[out]
```

The adapter wrapped this in a second layer: `vf = f"[0:v]{stacked_filter}[final]"`, creating:
```
[0:v][0:v]split=2[main][face];...;[v0][v1]vstack=inputs=2[out][final]
```

FFmpeg rejected this because `split` had 2 input labels but only 1 actual input.

**Fix:** Use the filtergraph directly with `-filter_complex` and `-map [out]`:
```python
cmd = [..., "-filter_complex", stacked_filter, "-map", "[out]", ...]
```

---

## Root Cause Summary

| # | Component | Impact | Fixed |
|---|-----------|--------|-------|
| 1 | `_render_gaming_stacked_via_ffmpeg` hardcodes full-frame | Both panels identical | ✅ |
| 2 | `ConcatRenderRequest` missing region fields | No way to pass regions | ✅ |
| 3 | `EditPlan.from_clip()` ignores crop_configs | Gaming data never read | ✅ |
| 4 | `EditPlan` missing gaming region fields | Data can't be carried | ✅ |
| 5 | `detect_encoder()` 3-tuple unpacked as 2 | All gaming renders fail | ✅ |
| 6 | `crop_converter.py` wrong docstring | Documentation confusion | ✅ |
| 7 | `-vf` used with `filter_complex` graph | All gaming renders fail | ✅ |
