# CONCAT CROP & SMART COMPOSITION V2 — Final Report

**Status:** COMPLETE  
**Date:** 2026-11-03  
**Scope:** Root cause investigation, API calibration, composition model, Gaming Stacked, 12 comparison renders, full audit documentation

---

## Executive Summary

The Concat adapter had two independent bugs that together caused all renders to produce letterboxed landscape video (black bars top/bottom) instead of portrait fill. Both bugs have been found, root-caused, and fixed. All 4 fixed (C) renders produce correct 1080×1920 portrait fill at exactly 20.0s. The FFmpeg pipeline is unchanged.

---

## Problems Found

### Bug 1 — Hardcoded `clip_id = "c1"`

**Severity:** Critical — all Concat renders broken

After `project.open`, Concat's internal IdMint counter is at 4 (tracks T1–T4 were already allocated). The first `addClip` mints ID "c5", not "c1". All Phase 2b operations (trimClip, frameClip, setClipTransform) used hardcoded `"c1"` → targeted a non-existent clip → silent no-ops → raw source exported at original 16:9 aspect → letterbox when placed in 9:16 canvas.

**Fix:** Phase 2a now reads `createdId` from the `addClip` response and uses it for all subsequent operations.

### Bug 2 — `trimClip(start)` timeline position offset

**Severity:** Critical — wrong duration on all head-trimmed renders

`trimClip(edge="start", delta=X)` removes X seconds from the clip's in-point but also advances the clip's **timeline position** by X seconds. For a source starting at t=797s, the clip moved to timeline position 797s. The export started at t=0, producing 797s of black followed by 20s of content (817s total).

**Fix:** Added `moveClips` operation after every `trimClip(start)` to reset the clip's timeline position back to 0.0.

---

## Fixes Implemented

Both fixes are in `integrations/concat/adapter.py`:

```python
# Bug 1 fix — Phase 2a reads createdId
add_result = batch_responses[add_idx]
clip_id = add_result.get("createdId") or add_result.get("result", {}).get("createdId")

# Bug 2 fix — Phase 2b resets timeline position after head trim
if head_delta > 0:
    # trimClip operation
    p2_reqs.append({..., "command": {"op": "trimClip", "clipId": clip_id,
                                      "edge": "start", "delta": head_delta, "ripple": False}})
    # moveClips reset
    p2_reqs.append({..., "command": {"op": "moveClips",
                                      "moves": [{"clipId": clip_id, "trackId": track_id, "start": 0.0}],
                                      "ripple": False}})
```

---

## API Calibration Results

See `API_GEOMETRY_CALIBRATION.md` for full details.

| Test | Result |
|------|--------|
| FrameClip("fill") geometry | PASS — scale=3.1605, corners cropped as expected |
| Trim accuracy (head + tail) | PASS — states confirmed: 5s→4s→3s |
| offsetX formula | VERIFIED — `(shift_px * scale) / canvas_w`, clamped ±3.0 |
| Export quality | PASS — correct dimensions, H.264 output |

---

## Gaming Stacked Layout

See `GAMING_STACKED_TESTS.md` for full details.

Concat's crop fractions interact with fill framing in a non-trivial way — the rendered zone boundaries for a two-track zone split did not match geometric predictions. After exhaustive testing (fill+crop and SetClipTransform approaches both failed), the decision was made to use FFmpeg as the rendering engine for Gaming Stacked presets.

**Implementation:** `ConcatAdapter.render()` detects `crop_preset` containing "GAMING_STACKED" and delegates to `_render_gaming_stacked_via_ffmpeg()`, which uses the same `_compute_stacked_fit_filter()` used by the main pipeline. Returns `engine_version = "0.2.8+ffmpeg-stacked"` for traceability.

**Split ratios tested:** 50/50, 60/40, 65/35, 70/30 — all correct via FFmpeg fallback.

---

## Comparison Renders

12 renders across 4 creators (3 variants each):

| Variant | Visual Result | Duration | Black bars |
|---------|---------------|---------|------------|
| A (FFmpeg current) | ✅ Portrait fill | 28–35s (natural) | None |
| B (Concat broken) | ❌ Letterboxed | 20s | ~32–36% top and bottom |
| C (Concat fixed) | ✅ Portrait fill | **20.0s exact** | None |

4/4 A frames: PASS  
4/4 B frames: FAIL (confirms pre-fix bug)  
4/4 C frames: PASS

---

## Face Focus

Planned but not implemented in V2. Infrastructure is in place (`EditPlan.keypoints`, `to_concat_request()` passthrough, `setClipKey` operations planned in adapter). Blocked by visual analyzer not yet emitting per-second face keypoints. See `FACE_FOCUS_TESTS.md`.

---

## Composition Model

`EditPlan` dataclass serves as a motor-independent representation of a clip render operation. The same structure drives either FFmpeg (current default) or Concat (experimental). See `COMPOSITION_MODEL.md`.

---

## Performance

- Concat debug build: ~21s per 20s clip (acceptable for experimental use)
- Release build estimated: ~3–7s (production-ready)
- moveClips fix adds <50ms overhead (single RPC call)

See `PERFORMANCE.md`.

---

## Regressions

**None.** FFmpeg pipeline is unchanged. All A renders pass visual QA. The Concat path is gated by `concat_enabled=True` and only invoked explicitly. See `REGRESSION_RESULTS.md`.

---

## What's Left

| Item | Status |
|------|--------|
| Bug 1 fix (createdId) | ✅ Done |
| Bug 2 fix (moveClips) | ✅ Done |
| Gaming Stacked (FFmpeg fallback) | ✅ Done |
| 12 comparison renders | ✅ Done |
| Full audit documentation (10 docs) | ✅ Done |
| Face Focus keyframe animation | 🔲 Planned (Phase 3) |
| Concat release build | 🔲 Optional |
| Re-process stale clip_variants | 🔲 Recommended |
| Library UI engine/version display | 🔲 Pending |
| Google Drive sync of reports | 🔲 Pending |

---

## Verdict

**The Concat adapter is production-ready for standard fill/crop clips.** Both root-cause bugs are fixed and verified across 4 creators. Gaming Stacked presets work correctly via FFmpeg fallback. The FFmpeg pipeline is unaffected. V2 scope is complete.
