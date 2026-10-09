# ContentEngine Audit Findings
_Audit date: 2026-10-09_

## Fixed Issues

### F-01: generate-top / generate-series missing QA call
**Severity:** HIGH  
**File:** `api/main.py:1817`, `api/main.py:1858`  
**Symptom:** 55 clips created via `/jobs/{id}/generate-top` had `visual_qa=PENDING`, `prepublish_decision=PENDING`, `prepublish_score=0.0` permanently. They appeared in Review with no score.  
**Root cause:** Both `generate_top_clips` and `generate_series_clips` call `render_clips_onepass` but never called `run_qa` or `run_prepublish_gate`.  
**Fix applied:** Added `run_qa` + `run_prepublish_gate` calls after render in both endpoints (same pattern as the main pipeline).  
**Backfill:** Applied `run_qa` + `run_prepublish_gate` to all 55 affected clips. All now show `visual_qa=PASS`, `prepublish_decision=REVIEW`.  
**Follow-up:** Applied `ensure_video_package_publications` to 5 affected videos — all 55 clips now have publications.

---

### F-02: Smart reframe face filter (plan_clip_v2)
**Severity:** HIGH (incorrect crop framing)  
**File:** `engine/reframe/planner.py`  
**Symptom:** Wrong x_offset (136 vs correct 792 for illojuan clip). BlazeFace detected tiny background faces (34–44px, 1156–1936 px²) on posters/screens in 53/73 proxy frames.  
**Root cause:** No minimum face size filter — background artifacts dominated EMA+median calculation.  
**Fix applied:** `_MIN_FACE_AREA_FRAC = 0.01` constant; filter eliminates faces < 2304 px² on 640×360 proxy. Real faces > 18000 px².  
**Status:** Fixed in previous session; validated end-to-end.

---

### F-03: framing_plan not persisted on accept (Alembic 0007)
**Severity:** MEDIUM  
**File:** `api/main.py:accept_reframe_variant`, `alembic/versions/a720229ca710_...py`  
**Symptom:** Reframe tab showed blank panel on re-open after accept. Accepted framing plan was lost.  
**Fix applied:**  
- Added `clips.framing_plan TEXT` column (migration 0007)  
- `accept_reframe_variant` now persists `plan_json` to `clips.framing_plan`  
- Reframe tab UI shows accepted state badge on re-open

---

### F-04: Ghost package item referencing non-existent publication
**Severity:** MEDIUM (referential integrity)  
**Symptom:** `clip_package_items` had `pub_id=fc80677f` referencing a publication that was deleted.  
**Fix applied:** Deleted orphan item in previous session.

---

### F-05: Ghost "published" publication for deleted clip
**Severity:** MEDIUM (status accuracy)  
**Symptom:** `publications` had status=`published` for `clip_id=0e1f4833` which no longer exists in `clips`.  
**Fix applied:** Marked publication as `failed` in previous session.

---

## Known Issues (Not Fixed)

### K-01: series_part=4 over-concentration (design flaw)
**Severity:** LOW (publishing inactive)  
**File:** `engine/analyzers/series_detector.py:_split_arc`  
**Symptom:** 706/1020 candidates have `series_part=4`; 226/489 publications at `series_part=4`.  
**Root cause:** `_split_arc` caps each part at `MAX_PART_S=45s`. For long arcs (>180s), parts 1–3 each get ~45s and part 4 absorbs the rest (e.g., 1486s for a 1621s arc). All candidates after the 180s mark get `part_num=4` by default.  
**Impact:** Series ordering in YouTube upload queue is wrong for long videos. Not blocking since publishing is inactive.  
**Recommendation:** Rewrite `_split_arc` to partition candidates evenly by count rather than by time duration, OR limit `MAX_NARRATIVE_GAP` to prevent arcs longer than `max_parts * MAX_PART_S`.

---

### K-02: 35 orphan publications (archived/failed)
**Severity:** LOW  
**Symptom:** `publications.clip_id` references clips no longer in `clips` table.  
**Detail:** 33 archived, 2 failed. All are historical records for clips that were later deleted.  
**Impact:** None — archived/failed publications are not shown in active workflows.  
**Recommendation:** Add ON DELETE CASCADE FK or periodic cleanup job.

---

### K-03: Review badge count capped at 200
**Severity:** LOW (UX only)  
**File:** `dashboard/index.html` + `api/main.py:/review/pending`  
**Symptom:** Review tab badge shows "200" when there are 472 REVIEW clips. The `/review/pending` endpoint has `max limit=200`, so the dashboard shows length of first page as the badge.  
**Recommendation:** Add a `GET /review/count` endpoint (or include total in response headers) and use it for the badge.

---

### K-04: 1 missing video file
**Severity:** LOW  
**Source:** `GET /storage/summary` → `missing_videos: 1`  
**Impact:** That specific video cannot be re-processed. Its clips still exist and are functional.  
**Recommendation:** Remove the stale video DB record if the file won't be restored.

---

### K-05: 7 publications in 'needs_check' status
**Severity:** LOW  
**Detail:** All are `youtube_shorts` platform, created between 2026-10-02 and 2026-10-08.  
**Impact:** These publications are flagged for manual review before upload. Not blocking.

---

### K-06: Recent job errors (403 from yt-dlp)
**Severity:** INFORMATIONAL  
**Detail:** 3 jobs failed with `HTTP Error 403: Forbidden` from yt-dlp. 1 job interrupted by server restart.  
**Impact:** Normal operational failures. The interrupted job (5b720e1d) is correctly marked FAILED.  
**Recommendation:** Implement automatic retry for 403 errors (could be rate-limiting); the current manual retry endpoint exists but is not triggered automatically.

---

## Audit Scope Not Covered

The following areas were not audited (see CLAUDE.md exclusions):
- Social publishing APIs (TikTok, Instagram, YouTube) — inactive, CLAUDE.md says do not touch
- Analytics collector — stub, inactive
- Learning/autopsy — stub, inactive  
- OAuth flows — present but never used
- Full caption editor E2E test
- Batch upload UI
- Bulk operations (bulk-delete, bulk-assign)
- Accessibility (axe-core scan) — deferred
