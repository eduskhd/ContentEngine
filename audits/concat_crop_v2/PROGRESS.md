# Progress Tracker

**Last updated:** 2026-11-03

---

## Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Root cause investigation | ✅ Done |
| 2 | API geometry calibration | ✅ Done |
| 3 | Composition model | ✅ Done |
| 4 | Gaming Stacked layout | ✅ Done (FFmpeg fallback) |
| 5 | Face Focus keyframes | 🔲 Planned (Phase 3, blocked) |
| 6 | 12 comparison renders | ✅ Done |
| 7 | Visual QA & contact sheets | ✅ Done |
| 8 | Audit documentation | ✅ Done |
| 9 | Library UI integration | 🔲 Pending |
| 10 | Google Drive sync | 🔲 Pending |

---

## Documents

| Document | Status |
|----------|--------|
| ROOT_CAUSE.md | ✅ Done |
| API_GEOMETRY_CALIBRATION.md | ✅ Done |
| COMPOSITION_MODEL.md | ✅ Done |
| GAMING_STACKED_TESTS.md | ✅ Done |
| FACE_FOCUS_TESTS.md | ✅ Done |
| RENDER_COMPARISON.md | ✅ Done |
| VISUAL_QA.md | ✅ Done |
| PERFORMANCE.md | ✅ Done |
| REGRESSION_RESULTS.md | ✅ Done |
| FINAL_REPORT.md | ✅ Done |
| PROGRESS.md | ✅ Done (this file) |

**11/11 documents complete.**

---

## Code Changes

| File | Change | Status |
|------|--------|--------|
| `integrations/concat/adapter.py` | Bug 1: read createdId from addClip response | ✅ Done |
| `integrations/concat/adapter.py` | Bug 2: moveClips after trimClip(start) | ✅ Done |
| `integrations/concat/adapter.py` | Gaming Stacked: FFmpeg fallback | ✅ Done |
| `integrations/concat/edit_plan.py` | Pass crop_preset to ConcatRenderRequest | ✅ Done |

---

## Evidence

| Item | Location |
|------|----------|
| 12 comparison renders | `audits/concat_crop_v2/evidence/renders/` |
| 12 frame captures | `audits/concat_crop_v2/evidence/*.png` |
| Calibration video | `experiments/calib_1920x1080_grid.mp4` |
| Calibration frames | `experiments/calib_fill_frame.png`, etc. |
| Gaming Stacked diagnostics | `experiments/stack_*.mp4`, `experiments/stack_*_frame.png` |
| Adapter e2e test | `experiments/calib_adapter_fixed.mp4` |

---

## Known Issues

1. **Stale clip_variants records:** Pre-V2 Concat renders in the DB have wrong duration and letterboxed content. Re-render required before any production use.
2. **Concat release build not compiled:** Current binary is debug. ~3–7× slower than release. Acceptable for experimental/testing use.
3. **iker_unzu timeout (early batch):** One early batch run timed out for iker_unzu (600s). Final batch produced correct 20.0s render. Debug build + long source video was the cause.
4. **Face Focus not implemented:** Visual analyzer does not emit per-second face keypoints. `EditPlan.keypoints` infrastructure exists but is unused.

---

## Next Actions (ordered by priority)

1. **Re-process stale clip_variants** — run the fixed adapter against all clips that have `render_engine='concat'` in clip_variants with wrong duration
2. **Compile release build** — `cargo build --release` → replace `tools/concat-cli.exe`
3. **Library UI** — show engine/version/preset per clip variant in dashboard clip modal
4. **Google Drive sync** — upload audit documents (not videos/DB) to folder `1J6P3WqZnrBPX2TLcvMwc-wi50RxIp162`
5. **Face Focus** — extend visual analyzer to emit per-second face keypoints (Phase 3)
