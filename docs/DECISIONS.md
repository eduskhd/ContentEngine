# Technical Decisions

Non-obvious choices recorded here so future sessions don't relitigate them.

---

## D-001 — SQLite instead of Postgres/Redis

**Decision:** Single SQLite file (`db/engine.sqlite`) with WAL mode for all persistence.

**Why:** Private tool running on one machine. No network, no connection pool overhead, no services to manage. WAL mode gives concurrent read performance without blocking writes. The `job_queue` table uses a Redis-compatible interface so it can be migrated later without touching the rest of the code.

---

## D-002 — Unified job_id (API + DB same UUID)

**Decision:** The `job_id` UUID is generated once in the API handler, passed to `process_video()` as `job_id=`, used in `db.create_job()`, and stored in `_jobs[job_id]`. One ID everywhere.

**Why:** Earlier builds generated separate IDs for the API response and the DB row, causing desync after restart. A restart would clear `_jobs` but the DB would have a different ID, making the job unrecoverable from the API.

---

## D-003 — `/jobs` reads DB first, overlays in-memory

**Decision:** `GET /jobs` queries `jobs LEFT JOIN videos` from SQLite, builds a dict keyed by job_id, then overwrites fields from `_jobs` where available.

**Why:** Pure in-memory reading meant jobs disappeared after restart. Pure DB reading missed live status updates (the worker updates DB at each step, but the API's in-memory copy has the full result object that hasn't been serialized to DB). The merge gives both persistence and live data.

---

## D-004 — `_has_audio_stream()` before any audio operation

**Decision:** In `engine/transcription.py`, run ffprobe to check for an audio stream before calling ffmpeg to extract audio or running whisper.

**Why:** ffmpeg exits with `"Output file does not contain any stream"` and returncode 1 when there's no audio, which crashed the pipeline for video-only files (screencasts, gameplay footage, etc.). The fix must be a pre-check, not error handling around ffmpeg, because ffmpeg's error output is not reliable enough to distinguish this case from real errors.

---

## D-005 — Position-based scoring for no-audio candidates

**Decision:** When `words == []`, candidate detector uses `score = 30.0 + position_score * 20.0` where `position_score = max(0.2, 1.0 - (start / duration) * 0.5)`. Earlier segments score higher.

**Why:** Without transcript, there is no semantic or hook signal. The only useful heuristic is that content creators typically front-load their best material. A uniform score would produce arbitrary clip selection; a position decay gives a predictable and reasonable result.

---

## D-006 — ASS format for captions (not SRT)

**Decision:** Caption burn-in uses ASS (Advanced SubStation Alpha) format, not SRT.

**Why:** SRT only supports group-level timing — you can't highlight individual words. ASS supports per-word timed events with inline override tags (`\c` for color, `\fscx\fscy` for scale). This is the standard approach for karaoke-style word-by-word highlighting in ffmpeg. SRT would require a completely different approach (baked-in rendering, no per-word control).

---

## D-007 — ASS color is BGR not RGB

**Decision:** `_hex_to_ass("#RRGGBB")` produces `&H{alpha}{B}{G}{R}` (blue-green-red, inverted alpha).

**Why:** ASS color format is `&HAABBGGRR` — the bytes are in reverse order from HTML hex. Getting this wrong produces wrong colors (e.g., yellow becomes blue). The `alpha` byte is inverted: `0x00` = fully opaque, `0xFF` = fully transparent (opposite of CSS opacity).

---

## D-008 — FAIL CLOSED QA gate

**Decision:** `technical_qa=FAIL` OR `visual_qa=FAIL` → `prepublish_decision=REJECT`. A clip must pass both checks to be publishable.

**Why:** False positives (passing a bad clip) are worse than false negatives (rejecting a good clip) for a clipping tool. A rejected clip can be manually approved via `POST /review/{id}/approve`. A published bad clip cannot be unpublished automatically.

---

## D-009 — Rights check always passes (rights_verified=1)

**Decision:** `db.create_video()` always sets `rights_verified=1`. The `/videos/{id}/verify-rights` endpoint exists but is never called automatically.

**Why:** This is a private tool for personal use. The rights verification API surface is kept for the schema completeness and potential future use, but it's not enforced because it would block every single job.

---

## D-010 — Canvas 2-pass draw (stroke then fill)

**Decision:** Caption canvas preview draws each word twice: first the full group with stroke color, then again with fill color.

**Why:** Single-pass drawing with stroke and fill combined causes the stroke to bleed over adjacent words' fill because CSS/Canvas applies stroke outward from the glyph center. Separating into stroke-only pass then fill-only pass gives clean outlines. This matches how libass renders captions internally.

---

## D-011 — One-pass render (trim + crop + caption in single FFmpeg call)

**Decision:** `engine/renderers/render_clip.py` performs trim, crop/scale, and ASS caption burn-in in a single FFmpeg invocation. The old approach used three sequential calls (clip_generator → reframer → caption_burner), each doing a full re-encode.

**Why:** Each FFmpeg encode of a 30–60s H.264 clip at 1080p takes 8–30s on CPU. Three sequential passes = 24–90s per clip. One pass = 8–30s per clip, plus parallel execution across clips. Measured improvement: 3–7× render speedup. Quality is identical (same CRF/quality setting, one encode means no generation loss from multiple transcodes).

---

## D-012 — Hardware encoding via `hw_accel.detect_encoder()`

**Decision:** `engine/hw_accel.py` probes for NVENC, then QSV, then falls back to `libx264 veryfast`. The result is `@lru_cache`d at module level and used by the one-pass renderer.

**Why:** Intel QSV (Quick Sync) is available on this machine. QSV offloads H.264 encode to the integrated GPU, freeing CPU cores for other pipeline stages. This also sets `max_parallel_renders=3` (vs 2 for CPU-only), allowing more clips to render simultaneously without saturating the system.

---

## D-013 — Transcript cache is path-based, not job-id-based

**Decision:** `engine/transcription.py` first checks `videos.words_json` by `video_id`, then falls back to a query `WHERE path=? AND words_json IS NOT NULL`. `engine/database.py` exposes `get_cached_words_by_path()` and `get_proxy_by_path()` for the same pattern on proxies.

**Why:** Each pipeline run creates a new `video_id` (because `ingest()` calls `db.create_video()` each time). A pure `video_id` cache would never hit on re-submissions of the same file. Path-based lookup means the second submission of the same video skips transcription entirely (0s vs 100–400s).

---

## D-014 — Analysis proxy: 360p 2fps for visual analysis

**Decision:** `engine/proxy.py` generates a 360p 2fps proxy for each video (ultrafast preset, no audio). Visual analyzer uses the proxy when available; falls back to master if proxy generation failed.

**Why:** The visual analyzer opens the video for each candidate window. On a 1920×1080 source, each frame decode is ~4× more work than 360p. With a proxy, the visual analysis is ~3–4× faster. The proxy is stored on disk and reused across jobs for the same source. Quality for motion/face detection is identical at 360p vs 1080p — these algorithms don't need high resolution.

---

## D-015 — Visual analysis: one VideoCapture open for all candidates

**Decision:** `analyze_visual()` opens a single `cv2.VideoCapture` for the analysis video (proxy or master) and seeks within it for each candidate, rather than opening/closing per candidate.

**Why:** `VideoCapture` construction is expensive (file open + index read + codec init). For 20 candidates, the old approach opened the file 20 times. With a single open, seek cost is proportional only to seek distance (fast on proxy, which has many I-frames due to ultrafast preset).

---

## D-016 — db.create_job() is idempotent when preset_id is provided

**Decision:** `db.create_job(preset_id=job_id)` now checks if the row already exists before INSERTing. If it exists (retry path), it returns the existing `job_id` without modification.

**Why:** On retry (`POST /jobs/{id}/retry`), the API resets the `jobs` row status to QUEUED and re-enqueues. When the worker calls `process_video(job_id=existing_id)`, the pipeline called `db.create_job(preset_id=existing_id)` which attempted a duplicate INSERT, failing with UNIQUE constraint. This made all retries fail silently. The fix makes the function safe to call multiple times for the same job_id.

---

## D-017 — Worker always updates jobs table on failure

**Decision:** `PipelineWorker._process()` now calls `db.update_job(jid, status="FAILED", error=...)` in its exception handler, regardless of where in `process_video()` the exception was raised.

**Why:** `process_video()` has its own try/except that updates the DB on failure. But if an exception was raised BEFORE the try block (e.g., during `db.create_job()` on a retry), the pipeline's except block never ran, leaving `jobs.status = QUEUED` while `_jobs` and `job_queue` showed FAILED. Now the worker is the authoritative updater as a safety net.

---

## D-018 — SSRF protection via validate_url() in downloader

**Decision:** `engine/downloader.py` now exports `validate_url(url)` which raises `ValueError` for URLs targeting private IPs (RFC 1918), loopback, link-local, reserved ranges, and known metadata endpoints (AWS, GCP). This is called at the start of `download_url()` and in `POST /jobs/from-url` before queueing.

**Why:** The platform accepts arbitrary URLs from the user. Without validation, an attacker (or misconfigured internal user) could use yt-dlp to make requests to internal infrastructure (metadata APIs, internal services, localhost admin panels). DNS rebinding attacks are not addressed (would require DNS resolution at validation time), but the direct IP ranges are blocked.

---

## D-019 — File upload size limit enforced by streaming check

**Decision:** `POST /jobs` enforces a 10 GB upload limit by reading the incoming file in chunks and counting bytes. If the limit is exceeded, the partial file is deleted and HTTP 413 is returned.

**Why:** FastAPI reads the entire file before the handler runs if `Content-Length` is trusted, but Content-Length can be spoofed. Streaming the file and counting bytes is the reliable approach. 10 GB is sufficient for typical video files and avoids filling disk.

---

## D-020 — Pagination added to /jobs and /review/pending

**Decision:** `GET /jobs` now accepts `limit` (default 100, max 500), `offset`, and `status` query parameters. `GET /review/pending` accepts `limit` (default 50) and `offset`.

**Why:** These endpoints previously returned all records with no limit. At 500+ jobs, returning all would cause latency and memory pressure. The dashboard JS already calls these endpoints on load — adding pagination prevents load degradation as the library grows.

---

## D-021 — Whisper "small" over "base" for word timestamps

**Decision:** `CONFIG.whisper_model = "small"` (was "base").

**Why:** "base" produces adequate transcription text but imprecise word-level timestamps, which directly hurts smart-cut boundary quality. "small" is ~40-50% slower in cold transcription (~420s vs ~300s) but produces significantly tighter word timestamps. The transcript cache (path-based) means this cost is paid once per source file — subsequent jobs on the same video use cached words instantly. The quality improvement to candidate detection and caption sync is worth the cold-start overhead for a private tool.

---

## D-022 — Intro/outro skip zones (3% each end)

**Decision:** Candidates whose sentence-peak falls entirely within the first 3% or last 3% of the video are discarded before scoring.

**Why:** The first 3% typically contains title cards, intro animations, and "welcome" preamble. The last 3% typically contains outro overlays, CTAs, and subscribe reminders. These produce well-detected "hook phrases" (e.g., "Today we're going to...") that score high but make terrible standalone clips. The 3% ratio is calibrated for videos ≥ 5 minutes; for shorter videos it's only a few seconds and causes minimal loss.

---

## D-023 — Caption confidence threshold (0.30)

**Decision:** Words with whisper `probability < 0.30` are excluded from captions (`CONFIG.caption_min_word_confidence`). They remain in the full transcript list used for candidate detection.

**Why:** Low-probability words are whisper's uncertain guesses, often garbled phonemes at word boundaries or background noise. Showing them as captions looks broken to viewers. The transcript list keeps them because their timing may still contribute useful structural information (pause detection, pacing). Captions only need the words that are actually correct.

---

## D-024 — Technical QA is real, visual QA stays PENDING

**Decision:** `technical_qa` in `render_clip.py` is now set by `_check_technical_qa()` (file size, video stream, duration, fps). `visual_qa` stays "PENDING".

**Why:** Technical QA can be determined by probing the output file with ffprobe — zero cost, fully automated. Visual QA (checking for black frames, motion quality, composition) requires frame-level analysis which would add meaningful latency to the render step. Since the existing QA module (`engine/qa/video_qa.py`) runs separately in step 12, visual QA is deferred there. The FAIL CLOSED rule applies to `technical_qa=FAIL` → REJECT, as before.
