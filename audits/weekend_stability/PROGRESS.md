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

### Gaming Compositor Verification (task: gaming_compositor_fix) ✅

**GAMING_STACKED_FIT: VISUALLY CONFIRMED WORKING**

- 8 jobs have GAMING_STACKED_FIT crop configs in DB
- All 8 have `gameplay_x` + `facecam_x` fields set correctly
- Jobs 179734c2, c6fa6cf9, 8dd96768, abf14566: clips created AFTER crop_config → stacked layout applied
- Job d1834ea0: clips created BEFORE crop_config → center crop (expected — crop_config added after)
- Test frame extracted from job 179734c2 at t=10s → `experiments/gaming_stacked_layout/VERIFY_stacked_frame.jpg`
- **Visual confirmation:** 1080x1920 frame, clear horizontal split (top content + bottom content), captions "Y DE YOUTUBE Y" in bottom panel safe zone
- `_compute_stacked_fit_filter()` builds valid FFmpeg filter: split→gameplay panel→facecam panel→vstack
- Stored `framing_plan` in candidates shows version=2 (expected — crop_config overrides at render time, not stored back to DB)

**BUG-002 discovered and fixed** (see ISSUES.md ISS-005):
- generate-top and generate-series didn't pass crop_config → gaming layout lost on those re-render paths
- Fixed: both endpoints now read and pass crop_config

### Library & Web API Audit (task: library_web_audit) ✅

**11/11 Library API endpoints: ALL OK**

| Endpoint | Result |
|----------|--------|
| GET /creators | OK — 25 creators |
| GET /creators/{id} | OK |
| GET /clips?limit=5 | OK |
| GET /clips?limit=5&page=2 | OK (pagination works) |
| GET /clips/{id} | OK — has render_engine field |
| GET /clips/{id}/variants | OK — count returned |
| GET /packages?limit=5 | OK — 99 packages |
| GET /packages/{id} | OK |
| GET /performance/summary | OK |
| GET /health | OK — 2/2 workers |
| GET /jobs?limit=3 | OK |

**DB final state:**
- 734 PASS clips, 0 FAIL, 8 PENDING (pre-QA era, no files)
- 32 Concat variants DONE
- 74 COMPLETED jobs, 14 FAILED jobs (historical)
- 25 creators, 76 videos, 1984 candidates

### Final Report Generated ✅

All 6 mission tasks complete. Final report at `audits/weekend_stability/FINAL_REPORT.md`.

**Verdict: PLATFORM HEALTHY — SAFE TO USE**
