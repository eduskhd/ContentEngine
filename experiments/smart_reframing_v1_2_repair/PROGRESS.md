# Smart Reframing V1.2 Repair — Progress Log

**Date:** 2026-10-19  
**Status:** COMPLETE — all renders, contact sheets, and tests done.

---

## Root cause summary

The original V1.2 experiment (`experiments/smart_reframing_v1_2/`) had four bugs:

| Bug | Description | Impact |
|-----|-------------|--------|
| **P1** | Used 9:16 pre-cropped V1.1 clips as input instead of 16:9 source files | Scene analysis ran on wrong aspect ratio |
| **P2** | P1 cascade: every clip classified `static_gameplay` (no face visible in 9:16 source) | Composition mode always SPLIT_LAYOUT |
| **P3** | `hud_penalty()` existed in `hud_protector.py` but was never called in `_optimal_gameplay_region()` | HUD regions had zero effect on crop scoring |
| **P4** | `plan_clip_v3_2()` computed one `dominant_scene_type()` for the whole clip; per-segment decisions not computed | Fine-grained temporal adaptation was absent |

---

## Fixes applied

**P1/P2** — `experiments/smart_reframing_v1_2_repair/run_experiment.py`:  
- Queries `videos.path` (16:9 source) and `videos.proxy_path` (360p 2fps proxy) from DB by `candidate_id`.
- Never reads from `experiments/smart_reframing_v1_2/clips/v1_1/` or any pre-cropped output.

**P3** — `engine/reframe/composition.py`:  
- `_optimal_gameplay_region()` now accepts `hud_regions=None`.
- Scoring loop calls `hud_penalty()` when `hud_regions` is provided: `score -= hud_pen * 0.25`.
- `decide_v12()` now accepts and passes `hud_regions` through to `_optimal_gameplay_region()`.

**P4** — `engine/reframe/planner.py`:  
- New Step 10b after main V1.2 decision: loops over each `SceneSegment` and calls `decide_v12()` per segment.
- Results stored as `plan["v12"]["segment_decisions"]` (list of dicts with `start_s`, `end_s`, `mode`, `scene_type`, `confidence`, `reason`, `split_fraction`).
- Full per-segment rendering is future work; this session covers analysis and storage.

---

## Experiment results

**18 renders completed** (6 clips × 3 variants: original, v1_1, v1_2_repair).

| Clip | V1.2 repair scene | Mode | HUD regions | Segments |
|------|-------------------|------|-------------|----------|
| Rubius_4ffe7a7c | static_gameplay | split_layout | 1 | 3 |
| AuronPlay_9e003b08 | **conversation** | **face_focus** | 5 | 3 |
| Rickyedit_2a3e3755 | **conversation** | **face_focus** | 6 | 1 |
| IlloJuan_04b85e28 | loading_or_transition | split_layout | 1 | 4 |
| IlloJuan_41bd5f73 | static_gameplay | split_layout | 2 | 5 |
| IlloJuan_d1378815 | static_gameplay | split_layout | 1 | 6 |

**Key observation:** AuronPlay and Rickyedit now correctly use `face_focus` mode (conversation scene).  
In the buggy V1.2 experiment, both were forced to `static_gameplay` / `split_layout` due to the 9:16 input (P1/P2).

---

## Tests added

File: `tests/test_reframing_v12_repair.py` — 9 tests, all passing.

| Test | Covers |
|------|--------|
| T81 | `_optimal_gameplay_region()` accepts `hud_regions=[]` (backward compat) |
| T81b | `_optimal_gameplay_region()` accepts `hud_regions=None` |
| T82 | HUD penalty > 0 when crop excludes HUD region |
| T82b | HUD penalty = 0 when crop fully contains HUD region |
| T82c | Excluding-HUD crop has higher penalty than including-HUD crop |
| T83 | `decide_v12()` accepts `hud_regions` without error |
| T83b | Face-dominant scene (`conversation`) returns `face_focus` regardless of `hud_regions` |
| T84 | `plan_clip_v3_2()` includes `segment_decisions` in `plan["v12"]` |
| T85 | Each `segment_decisions` entry has `start_s`, `end_s`, `mode`, `scene_type` |

---

## Files created / modified

| File | Change |
|------|--------|
| `engine/reframe/composition.py` | P3 fix: `hud_regions` param in `_optimal_gameplay_region()` + HUD penalty in score |
| `engine/reframe/planner.py` | P3 caller + P4: Step 10b per-segment decisions |
| `experiments/smart_reframing_v1_2_repair/run_experiment.py` | NEW |
| `experiments/smart_reframing_v1_2_repair/generate_contact_sheets.py` | NEW |
| `experiments/smart_reframing_v1_2_repair/PROGRESS.md` | NEW |
| `experiments/smart_reframing_v1_2_repair/manifest.json` | GENERATED |
| `experiments/smart_reframing_v1_2_repair/clips/original/` | 6 MP4 renders |
| `experiments/smart_reframing_v1_2_repair/clips/v1_1/` | 6 MP4 renders |
| `experiments/smart_reframing_v1_2_repair/clips/v1_2_repair/` | 6 MP4 renders |
| `experiments/smart_reframing_v1_2_repair/contact_sheets/` | 6 PNG sheets |
| `tests/test_reframing_v12_repair.py` | NEW — 9 tests |

---

## Next steps

- Visual review of contact sheets: compare `V1.1` vs `V1.2 Repair` columns.
- Per-segment rendering (future): wire `segment_decisions` into render path so each segment uses its own composition mode.
- Drive sync: push contact sheets to Google Drive folder `1J6P3WqZnrBPX2TLcvMwc-wi50RxIp162`.
