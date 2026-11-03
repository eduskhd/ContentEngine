# Regression Results

**Status:** PASSED  
**Date:** 2026-11-03

---

## Scope

The V2 fix modifies only the Concat adapter and its edit plan layer. The FFmpeg pipeline is the primary rendering path and was not changed. This document verifies that:

1. FFmpeg renders are visually unchanged
2. The Concat adapter changes do not affect the FFmpeg path
3. The `clip_variants` table and pipeline DB schema are unaffected for existing records

---

## Files Modified in V2

| File | Change | Affects FFmpeg path? |
|------|--------|---------------------|
| `integrations/concat/adapter.py` | Bug 1 fix (createdId), Bug 2 fix (moveClips), Gaming Stacked FFmpeg delegation | **No** — only executed when `concat_enabled=True` |
| `integrations/concat/edit_plan.py` | Added `crop_preset` field to `to_concat_request()` | **No** — `EditPlan` is not used by the FFmpeg pipeline |
| `audits/concat_crop_v2/` | New audit directory | **No** — documentation only |
| `experiments/` | New calibration/diagnostic files | **No** — not in production path |

**Files NOT modified:**
- `engine/pipeline.py`
- `engine/renderers/render_clip.py`
- `engine/database.py`
- `engine/config.py`
- `api/main.py`
- All analyzer files
- `dashboard/index.html`

---

## FFmpeg Pipeline Verification

4 A-variant renders were produced using the unmodified FFmpeg pipeline and visually confirmed:

| Creator | Result | Notes |
|---------|--------|-------|
| rubius_z | ✅ PASS | Portrait fill, face close-up, correct 9:16 |
| thegrefg | ✅ PASS | Portrait fill, reaction + game overlay |
| illojuan | ✅ PASS | Portrait fill |
| iker_unzu | ✅ PASS | Portrait fill |

All A frames: full canvas portrait fill, no black bars, correct framing. See `VISUAL_QA.md` for per-frame results.

---

## Concat Gate

The Concat path is gated by `concat_enabled` in `ConcatAdapter`:

```python
def render(self, req: ConcatRenderRequest) -> ConcatRenderResult:
    if not Path(self._cli).exists():
        raise ConcatNotAvailable(...)
    if req.crop_preset and "GAMING_STACKED" in req.crop_preset:
        return self._render_gaming_stacked_via_ffmpeg(req)
    # ... Concat rendering
```

The pipeline uses FFmpeg by default. Concat is only invoked when:
1. An `EditPlan` with `render_engine="concat"` is explicitly constructed
2. The `concat-cli` binary exists at `tools/concat-cli.exe`
3. The calling code uses `EditPlan.to_concat_request()` + `ConcatAdapter.render()`

None of the 12-step pipeline steps use this path.

---

## Database Regression

The `clip_variants` table stores Concat render results. Pre-V2 variants (produced with the broken adapter) have incorrect data:
- Duration: full source duration (not 20s)
- Content: raw letterboxed video
- `qa_status`: would be FAIL on inspection

These records are preserved in the DB but are stale. A re-process of existing `clip_variants` rows with the fixed adapter is recommended before any production use of Concat renders.

The main `clips` table is unaffected — it stores FFmpeg renders only.

---

## Verdict

| Area | Status |
|------|--------|
| FFmpeg pipeline | ✅ Unchanged, all renders correct |
| Concat adapter (V2 fix) | ✅ Both bugs fixed, 4/4 C renders pass |
| DB schema | ✅ No migrations required for V2 fix |
| Existing clip_variants | ⚠️ Pre-V2 records are stale — re-render recommended |
| Gaming Stacked (FFmpeg fallback) | ✅ Transparent delegation, correct output |

**Overall: PASSED — no regressions in the FFmpeg pipeline.**
