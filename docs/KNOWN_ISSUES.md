# Known Issues

Issues here are real but do not block the core pipeline (VIDEO → CLIPS → DOWNLOAD). They are parked until they become worth fixing.

---

## KI-SEC-001 — No authentication on any API endpoint (by design for private tool)

**Status:** Accepted risk — private single-user tool, now bound to 127.0.0.1.
All 80+ REST endpoints are unauthenticated. Any process running on the same machine with localhost access can read, modify, or delete all data. If the tool is ever exposed on a network (e.g. via SSH tunnel, reverse proxy, or 0.0.0.0 binding), add token-based auth via FastAPI's `APIKeyHeader` dependency.

**Mitigations applied:** binding changed to 127.0.0.1; CORS restricted to localhost origins.

---

## ~~KI-SEC-002 — Dynamic SQL column-name interpolation in update_* helpers~~ FIXED 2026-09-15

Column allowlists (`frozenset`) are enforced inside `update_video`, `update_candidate`, `update_clip`, `update_creator`, `update_publication` in `engine/database.py`. Unknown column names raise `ValueError` before SQL is built. `update_job` uses fixed parameter names (no dynamic column interpolation).

---

## KI-SEC-003 — Admin and health endpoints expose operational details without auth

**Endpoints:** `GET /health`, `GET /admin/status`, `GET /admin/orphans`.
**Risk:** Returns worker status, recent job errors, disk usage, DB record counts. No sensitive user data exposed, but useful for reconnaissance on a networked deployment.
**Mitigation:** Acceptable for localhost-only tool. Add auth if ever network-exposed.

---

## ~~KI-000 — "database is locked" crashes pipeline~~ FIXED 2026-09-08

SQLite connections now use `timeout=30` + `PRAGMA busy_timeout=30000`. `caption_burner.py` and `reframer.py` no longer hold DB connections while ffmpeg runs. `db.init_db()` removed from `process_video()`.

---

## ~~KI-001 — Zombie jobs after server crash~~ FIXED 2026-09-09

`WorkerPool.start()` now runs `_cleanup_zombie_jobs()` before starting worker threads. Any job with a non-terminal status (`NOT IN ('COMPLETED','FAILED','QUEUED')`) is immediately set to `FAILED` with error `"Server restarted — job was interrupted"`.

---

## ~~KI-002 — ZIP download uses temp file that is never cleaned up~~ FIXED 2026-09-10

Both `GET /jobs/{id}/download-all` and `GET /publications/download-zip` now use `BackgroundTasks` to delete the temp `.zip` file after the response is sent. The `delete=False` is still needed for `FileResponse`, but cleanup is guaranteed via the background task.

---

## ~~KI-004 — Ghost clips from fake test jobs pollute Review tab~~ FIXED 2026-09-21

36 fake FAILED jobs (`/fake/path.mp4`) and their 36 associated ghost clips were archived to `_archived_*` tables. `GET /review/pending` now uses `JOIN videos` (not LEFT JOIN), so orphaned clips are excluded. Restore with `python cleanup_ghost_data.py --restore`.

---

## KI-003 — Caption word timestamps missing for pre-caption clips

**Symptom:** Clips that were generated before the caption system was added have `caption_data=NULL`. Opening them in the caption editor shows 0 words and the canvas preview is blank. Re-render produces a copy without captions.

**Root cause:** Word timestamps are only saved at pipeline step 12. Old clips were never processed through this step.

**Workaround:** To recover, delete the clip and re-run the job. Or accept that old clips will have no captions.

**Fix path:** If re-transcription is desired, add a `POST /clips/{id}/retranscribe` endpoint that re-runs transcription for the source video and re-saves word data for the clip's time window.

---

## ~~KI-004 — SSE job progress stream requires job to be in-memory~~ FIXED 2026-09-09

The SSE generator now falls back to DB when `job_id` is not in `_jobs`. If found in DB, it immediately emits one final event with the stored status (`completed` or `failed`) and closes the stream. If not found anywhere, it emits `{"error": "job not found"}`.

---

## KI-005 — Re-render uses source `output_path`, not original clip

**Symptom:** Re-rendering captions overwrites `_captioned.mp4` using `output_path` (the non-captioned clip) as source. If `output_path` was deleted manually, re-render fails with 400.

**Root cause:** `POST /clips/{id}/re-render` correctly reads from `row["output_path"]` (the reframed, pre-caption file). This is intentional. But it depends on that file still being on disk.

**Workaround:** Keep `output_path` files. They are the source of truth.

---

## KI-006 — Dashboard canvas preview not pixel-perfect vs burned captions

**Symptom:** The canvas overlay in the modal looks slightly different from the actual burned-in captions in the downloaded MP4 (font rendering, scale, anti-aliasing).

**Root cause:** Canvas 2D API renders with browser font engine. ffmpeg/ASS renders with libass. They use different font rendering pipelines. This is an inherent difference, not a bug.

**Impact:** Low — the preview is a faithful approximation for editing purposes.

---

## KI-007 — Duplicate URL submissions create two independent jobs

**Symptom:** Submitting the same URL twice (e.g., double-click, two browser tabs) creates two `jobs` rows and runs two full pipelines.

**Partial mitigation:** yt-dlp skips re-download if the output file exists; transcript cache skips re-transcription if the same path was processed before. The second job is fast (warm run), but it still creates duplicate DB records.

**Partial fix (C-001):** `POST /jobs/from-url` now returns the existing non-failed job_id if the same URL was already submitted — prevents duplicate from the URL flow. File upload path (POST /jobs) does not have this deduplication.

---

## ~~KI-008 — No authentication on any endpoint~~ Duplicate of KI-SEC-001

See KI-SEC-001. Removed as duplicate.

---

## KI-009 — No multi-user / workspace isolation

**Symptom:** All creators, videos, clips, publications are shared globally. No concept of ownership.

**Status:** Accepted for Phase 2.5. Required before external user onboarding.

**Fix path:** Add `workspace_id` or `user_id` foreign key to `creators`, `videos`, `jobs`, `clips`, `publications`. Add ownership filter to all queries. Add middleware to enforce isolation.

---

## ~~KI-011 — LLM analysis requires ANTHROPIC_API_KEY to be set manually~~ PARTIALLY FIXED (B-003)

`GET /health` now returns `llm_enabled: bool`. The dashboard header shows "✦ LLM ON" (green) or "LLM OFF" (gray) so the user can see at a glance whether LLM analysis is active.

**Remaining:** The system falls back to heuristic-only scoring without logging why. Acceptable for a private tool.

**To enable:** Set `ANTHROPIC_API_KEY` in environment before starting server:
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python server.py
```

---

## ~~KI-012 — Two videos sharing same job_id causes FK cascade failure on delete~~ FIXED 2026-09-12

When two `videos` records point to the same `job_id`, calling `_delete_video_cascade` on the first video deletes the job. Deleting the second video then raises `sqlite3.IntegrityError: FOREIGN KEY constraint failed` when trying to delete the same (already-gone) job, rolling back the entire transaction.

Fixed in `engine/database.py:_delete_video_cascade` — now checks `COUNT(*)` of remaining videos for the job before issuing `DELETE FROM jobs`. Only deletes the job if this is the last referencing video.

---

## KI-010 — Retryable vs non-retryable errors not distinguished

**Symptom:** All pipeline failures use the same retry logic (max 3 attempts). Invalid video format will be retried 3 times before giving up, wasting time.

**Fix path:** Add error category to `jobs` table. Classify errors in the pipeline:
- `RETRYABLE`: network timeout, OOM, temporary provider error
- `PERMANENT`: invalid format, unsupported codec, video too short

Permanent errors should not be retried.

---

## KI-013 — Missing video file `drafteados_ms8nxjbhfki.mp4`

**Status:** Known, non-critical.
**Symptom:** `GET /storage/summary` reports 1 missing video. DB has a record for `output/downloads/drafteados_ms8nxjbhfki.mp4` but the file was deleted manually.
**Impact:** The corresponding job cannot be re-processed. Its clips (if any) are unaffected. The entry appears in `/admin/orphans`.
**Fix path:** Either delete the orphaned `videos` record manually via `DELETE FROM videos WHERE path LIKE '%drafteados%'`, or restore the file from backup.

---

## KI-014 — No file backup mechanism

**Status:** Accepted risk for solo local tool.
**Symptom:** No automated backup of downloaded videos or rendered clips. Loss of disk = loss of all original footage.
**Fix path:** See `docs/ALMACENAMIENTO_ACTUAL.md` for a robocopy or R2/B2 cloud storage plan.
