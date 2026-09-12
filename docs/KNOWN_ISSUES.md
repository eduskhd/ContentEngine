# Known Issues

Issues here are real but do not block the core pipeline (VIDEO → CLIPS → DOWNLOAD). They are parked until they become worth fixing.

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

**Fix path:** Add a duplicate URL check in `POST /jobs/from-url` — query `jobs` by `source_path` for URL jobs. If a running or completed job exists for the same URL, return that job_id instead of creating a new one.

---

## KI-008 — No authentication on any endpoint

**Symptom:** All API endpoints are public. Anyone with network access to port 8000 can read, modify, or delete all data.

**Status:** Accepted for Phase 2.5 (internal tool, localhost). Required before exposing to external users.

**Fix path:** Add API key authentication middleware in `api/main.py` or reverse proxy with auth (nginx + basic auth).

---

## KI-009 — No multi-user / workspace isolation

**Symptom:** All creators, videos, clips, publications are shared globally. No concept of ownership.

**Status:** Accepted for Phase 2.5. Required before external user onboarding.

**Fix path:** Add `workspace_id` or `user_id` foreign key to `creators`, `videos`, `jobs`, `clips`, `publications`. Add ownership filter to all queries. Add middleware to enforce isolation.

---

## KI-011 — LLM analysis requires ANTHROPIC_API_KEY to be set manually

**Symptom:** `engine/analyzers/llm_analyzer.py` is silent when no API key is present — the system falls back to heuristic-only scoring without any log message visible in the dashboard.

**Impact:** Low — heuristic scores still work. But users may not realize LLM enhancement is disabled.

**Fix path:** Add `llm_enabled: bool` flag to `GET /health` response so the dashboard can show "LLM: enabled/disabled" status.

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
