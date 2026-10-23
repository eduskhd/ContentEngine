# Weekend Stability Mission — Progress Log

## 2026-10-23 — Session Start

### Context (from last conversation)
Fixes already applied before the weekend mission started:

1. **crop_converter.py** — x_offset formula corrected (center-crop reference was wrong by ~0.5 canvas widths)
2. **api/main.py: /clips/{id}/render-concat** — now reads framing_plan from candidates table (was always x_offset=0)
3. **engine/reframe/planner.py** — _MIN_FACE_AREA_FRAC lowered from 0.01 to 0.003
4. **api/main.py: /jobs/{id}/generate-top** — fixed sqlite3.Row.get() crash (video = dict(video))
5. **api/main.py: /jobs/{id}/generate-series** — same Row.get() fix
6. **api/main.py: SSE handler** — enriched DB-only completed jobs with source_title + clip_count
7. **dashboard/index.html** — suppressed banner for already-done jobs (already_done flag)
8. **GTA4 job 36499131** — 15 clips rendered, all QA=PASS/PASS via generate-top endpoint

### DB State at Mission Start
- Total clips: 752
- QA breakdown: PASS/PASS=734, PENDING/PENDING=8, WARN/PASS=10
- clip_variants (Concat): 31 rows, all status=DONE
- Tables: 38 including clip_variants, reframe_variants, collections

### Known Issues Going In
- GTA4 job (36499131) still shows status=COMPLETED with stale error "Server restarted..." — cosmetic only, clips are present
- Some clips with PENDING/PENDING QA — need investigation

---

## 2026-10-23 — Session Work (in-session loop)

### Crop & Concat Audit (task: crop_audit_fix) ✅

**crop_converter.py formula: VERIFIED**
- center (x_offset=656) → offsetX=+0.0000 PASS
- far-left (x_offset=0) → offsetX=+1.0798 PASS
- far-right (x_offset=1312) → offsetX=-1.0798 PASS
- All 5 test cases pass

**Concat render test: VERIFIED**
- Clip cc388b39 (GTA4, x_offset=656): render_status=DONE, 1080x1920 h264 30fps AAC, 5.8MB
- ffprobe confirms correct dimensions and audio
- Variant ID: 3881ef56

**Framing plan audit:**
- GTA4 clips (15 total): version=2, fallback=center, x_offset=656 (center crop correct for gameplay-only video)
- 10 clips total have framing_plan stored; 140+ clips use implicit center crop (no framing_plan)
- No clips with split_layout/GAMING_STACKED_FIT in framing_plan (those use crop_configs, see below)

### Bug Found & Fixed: generate-top/generate-series ignore crop_config

**Bug**: `POST /jobs/{id}/generate-top` and `generate-series` did not pass `crop_config` to renderer.
**Impact**: Any job with a GAMING_STACKED_FIT manual crop config would get center-cropped clips when re-rendered via generate-top, instead of the intended stacked layout.
**Fix**: Both endpoints now call `dbmod.get_crop_config(job_id)` and pass result to `render_clips_onepass()`.
**File**: `api/main.py` (both generate-top ~line 2112 and generate-series ~line 2184)

### Pipeline Health: CLEAN
- Orphaned candidates: 0
- Orphaned clips: 0
- Orphaned clip_variants: 0
- Zombie jobs: 0
- Missing output files (200 PASS clips sampled): 0
- All 6 tested API endpoints: OK

### Issue Found: 8 PENDING QA clips with missing files
- 8 clips from 2026-09-17 have technical_qa=PENDING and no output file
- These predate the QA gate implementation
- Cannot be fixed without modifying clip records (constraint blocks this)
- Documented in ISSUES.md as ISS-004
- They will not appear in review/approval flows as PASS clips (they're excluded by QA filter)

### Dashboard/Library Audit: HEALTHY
- Engine badges working (FFmpeg/Concat shown on clips)
- Variant bar in clip modal shows all Concat variants
- `/clip-variants/{id}/video` endpoint exists for streaming
- No broken fetch calls found in dashboard JS
- Correct endpoint: `/creators` (not `/library/creators` — fixed in supervisor prompts)

### Supervisor: BUILT & MECHANICALLY VERIFIED
- 15/15 mechanical tests pass (lock, checkpoint, recovery, stop signal, atomic save)
- Recovery from interrupted sessions: TESTED (running→pending on restart)
- Blocker: autonomous `claude --print` blocked by auto-mode classifier
- See BLOCKERS.md for workaround options

### Summary of all fixes in this session
1. api/main.py: generate-top + generate-series pass crop_config to renderer
2. api/main.py: generate-top + generate-series use dict(video) for .get() calls
3. Previously (same day): SSE banner enrichment, reprocess deleted video fix
4. Previously (same day): crop_converter formula, render-concat x_offset fix, face threshold

<!-- Supervisor will append new entries below this line -->
