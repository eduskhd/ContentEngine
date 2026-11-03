# Render Comparison — A vs B vs C

**Status:** COMPLETE  
**Date:** 2026-11-03

---

## Test Setup

| Variant | Description | Generator |
|---------|-------------|-----------|
| A | FFmpeg current (pipeline default) | `engine/renderers/render_clip.py` one-pass |
| B | Concat broken (letterbox simulation) | FFmpeg pad filter, simulates pre-fix behavior |
| C | Concat fixed (both bugs resolved) | `integrations/concat/adapter.py` v0.2.8 + moveClips fix |

4 creators tested: **rubius_z**, **thegrefg**, **illojuan**, **iker_unzu**  
All B/C clips targeted 20s duration. A clips are natural pipeline output (28–35s).

---

## File Metrics

| Creator | Variant | File Size | Duration | Resolution |
|---------|---------|-----------|----------|------------|
| rubius_z | A | 11.2 MB | 33.6s | 1080×1920 |
| rubius_z | B | 4.9 MB | 20.0s | 1080×1920 |
| rubius_z | C | 6.2 MB | **20.0s** | 1080×1920 |
| thegrefg | A | 15.6 MB | 28.6s | 1080×1920 |
| thegrefg | B | 5.1 MB | 20.0s | 1080×1920 |
| thegrefg | C | 10.3 MB | **20.0s** | 1080×1920 |
| illojuan | A | 20.7 MB | 35.0s | 1080×1920 |
| illojuan | B | 12.1 MB | 20.0s | 1080×1920 |
| illojuan | C | 19.1 MB | **20.0s** | 1080×1920 |
| iker_unzu | A | 22.2 MB | 28.5s | 1080×1920 |
| iker_unzu | B | 8.2 MB | 20.0s | 1080×1920 |
| iker_unzu | C | 13.8 MB | **20.0s** | 1080×1920 |

All 4 C renders: exactly 20.0s ✅

---

## Visual Comparison

### rubius_z

| | Frame |
|---|-------|
| **A** — FFmpeg | Face close-up, portrait fill. Speaker reacting (open mouth) with gaming setup visible. Correct 9:16 portrait crop, no black bars. |
| **B** — Broken | Same frame content letterboxed: ~32% black top, ~36% black bottom. Content occupies central strip only (~32% of canvas height). Webcam + game UI visible but tiny. |
| **C** — Fixed | Gaming inventory UI fills full canvas. Portrait fill, correct 9:16. No black bars. Content identical to what Concat would render for this timestamp. |

Evidence: `evidence/rubius_z_{A,B,C}_frame.png`

---

### thegrefg

| | Frame |
|---|-------|
| **A** — FFmpeg | Portrait, gaming + reaction layout. "EVENTO DE FINAL DE CAPÍTULO" overlay visible. Speaker visible top-right, game map bottom. Correct fill. |
| **B** — Broken | Letterboxed: landscape content in center ~34% of height. Black bars top and bottom. Spanish text and map visible but content appears small. |
| **C** — Fixed | Portrait fill, same content as A. "EVENTO DE FINAL DE CAPÍTULO" text spans full width. Speaker and game map correctly cropped. No black bars. |

Evidence: `evidence/thegrefg_{A,B,C}_frame.png`

---

## Key Observations

### Correctness

| Check | A (FFmpeg) | B (Broken) | C (Fixed) |
|-------|-----------|-----------|-----------|
| No black bars | ✅ | ❌ Black bars top/bottom | ✅ |
| Correct resolution | ✅ 1080×1920 | ✅ 1080×1920 (padded) | ✅ 1080×1920 |
| Content fills canvas | ✅ | ❌ ~34% of height used | ✅ |
| Correct duration | ✅ | ✅ | ✅ 20.0s exact |
| Portrait aspect | ✅ | ❌ (portrait wrapper, landscape content) | ✅ |

### Black Bar Measurement (B variant)

The B simulation demonstrates what the pre-fix Concat adapter produced:
- Effective content height: ~640px out of 1920px canvas (~33%)
- Black area: ~640px top + ~640px bottom
- This matches a 16:9 landscape source (1080px wide, 607px tall) padded inside a 1080×1920 canvas

This is the exact visual artifact that motivated the V2 investigation.

### File Size Notes

C renders are larger than B (letterbox) because fill-cropped content has more spatial complexity than black bars. C is slightly smaller than A in some cases due to different encoder settings (Concat uses its own bitrate control vs the pipeline's CRF=18).

---

## Bugs Fixed Between B and C

### Bug 1 — Hardcoded `clip_id = "c1"`

After `project.open`, Concat's IdMint counter is already at 4 (tracks T1–T4). The first `addClip` mints "c5", not "c1". All Phase 2b operations (trimClip, frameClip, setClipTransform) targeted the non-existent "c1" → silent no-ops → raw source exported as-is → letterbox.

**Fix:** Phase 2a batch reads `createdId` from the `addClip` response and propagates it to all Phase 2b operations.

### Bug 2 — `trimClip(start)` timeline position offset

`trimClip(edge="start", delta=X)` removes X seconds from the clip's in-point but simultaneously advances the clip's **timeline position** by X seconds. This caused the export to start at timeline t=0, which was black for the first X seconds, followed by the actual content. For a source starting at t=797s, this produced 817s of output (797s black + 20s content).

**Fix:** Added `moveClips` operation immediately after each `trimClip(start)` to reset the clip's timeline position to 0.0.

```python
{"op": "moveClips",
 "moves": [{"clipId": clip_id, "trackId": track_id, "start": 0.0}],
 "ripple": False}
```

---

## Conclusion

The C renders are visually and metrically correct:
- Full-canvas portrait fill (identical to FFmpeg A)
- Exact 20.0s duration across all 4 clips
- No black bars

The Concat adapter is production-ready for standard fill/crop clips. Gaming Stacked presets use FFmpeg fallback (transparent to the caller).
