# Smart Reframing V1.2 Repair — Final Report

**Date:** 2026-10-19  
**Status:** COMPLETE

## Summary

This experiment fixed four bugs in the V1.2 reframing engine and validated the fixes with 18 renders across 6 clips.

## What was fixed

**P1/P2 (input error):** The original V1.2 experiment used 9:16 pre-cropped clips as input for a horizontal-source analysis engine. All clips were misclassified as `static_gameplay` because no face was visible in the wrong-aspect-ratio input. This experiment uses 16:9 source files directly from the DB (`videos.path`).

**P3 (HUD penalty not wired):** `hud_penalty()` was computed but never subtracted from crop candidate scores. Fixed in `engine/reframe/composition.py` — HUD penalty now applies a 0.25-weight term in `_optimal_gameplay_region()`.

**P4 (no per-segment decisions):** Only one composition decision was made for the whole clip. Now `plan_clip_v3_2()` computes per-segment `decide_v12()` calls and stores results as `plan["v12"]["segment_decisions"]`.

## Key results

| Clip | Old scene (buggy) | New scene (repaired) | Old mode | New mode |
|------|-------------------|----------------------|----------|----------|
| Rubius | static_gameplay | static_gameplay | split_layout | split_layout |
| AuronPlay | static_gameplay | **conversation** | split_layout | **face_focus** |
| Rickyedit | static_gameplay | **conversation** | split_layout | **face_focus** |
| IlloJuan_04b85e28 | static_gameplay | loading_or_transition | split_layout | split_layout |
| IlloJuan_41bd5f73 | static_gameplay | static_gameplay | split_layout | split_layout |
| IlloJuan_d1378815 | static_gameplay | static_gameplay | split_layout | split_layout |

AuronPlay and Rickyedit now correctly use `face_focus` mode for their conversation segments.

## Tests

9 new tests in `tests/test_reframing_v12_repair.py` (T81–T85). All passing.

## Artifacts

- `clips/original/` — 6 center-crop baseline renders
- `clips/v1_1/` — 6 V1.1 renders
- `clips/v1_2_repair/` — 6 V1.2 repair renders
- `contact_sheets/` — 6 side-by-side PNG contact sheets
- `manifest.json` — full render manifest with timing and scene metadata
- `PROGRESS.md` — detailed change log
