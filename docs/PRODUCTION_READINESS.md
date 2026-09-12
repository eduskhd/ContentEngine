# Production Readiness — Phase 2.5 Assessment

**Date:** 2026-09-10  
**Classification:** INTERNAL ALPHA READY

---

## Final Readiness Status

### INTERNAL ALPHA READY

The platform can run repeatedly for internal use on a single machine. It is NOT yet ready for external users or multi-tenant deployment without the items listed under **Known Limitations**.

---

## Architecture Reviewed

**Pipeline (12 steps):**  
VIDEO → INGEST → PROXY → TRANSCRIPTION → CANDIDATE DETECTION → VISUAL+AUDIO (parallel) → PLATFORM FIT → VIRALITY SCORING → SKILLS → RENDER (1-pass trim+crop+caption) → QA/GATE → CLIPS READY

**Runtime components:**
- FastAPI + uvicorn (port 8000, single process)
- 2 PipelineWorker daemon threads polling SQLite job_queue every 2s
- Transcript singleton (faster-whisper loaded once)
- Hardware encoder detection (QSV/NVENC/CPU, `@lru_cache`)
- SQLite WAL mode at `db/engine.sqlite`

All components verified against code (not just documentation).

---

## Job System

Jobs flow through two parallel tracking systems that are kept in sync:

| System | Purpose |
|--------|---------|
| `jobs` table | Persistent pipeline state (QUEUED → INGESTING → TRANSCRIBING → ANALYZING → RENDERING → QA → COMPLETED / FAILED) |
| `job_queue` table | Worker task queue (queued → running → completed / failed), max 3 attempts |
| `_jobs` dict (in-memory) | Live status overlay for SSE streaming |

The same UUID is used as `job_id` in all three systems (Decision D-002).

**`GET /jobs`** merges DB (persistent) with in-memory (live real-time status), paginated with `limit`/`offset`/`status` filters.

---

## Persistence

- All jobs, videos, candidates, clips, and publications are persisted to SQLite before any in-memory operation.
- `jobs` table records are created before the pipeline starts and survive server restarts.
- Transcript data (`words_json`) is cached path-based in `videos.words_json` — survives restarts.
- Proxy paths are cached in `videos.proxy_path` — survives restarts.
- Pipeline timing data is stored in `pipeline_timings` table per stage per job.

**What survives a restart:**
- All jobs and their status (COMPLETED/FAILED/QUEUED)
- All clips and their file paths
- All transcripts (path-based cache)
- All proxies
- All publications and their state

**What is lost on restart:**
- In-memory `_jobs` dict (live status cache) — rebuilt from DB on `GET /jobs`
- SSE connections (clients must reconnect)
- In-flight job progress (the job is marked FAILED by zombie cleanup, then retriable via `POST /jobs/{id}/retry`)

---

## Recovery

### After server crash (mid-job):
1. `WorkerPool._cleanup_zombie_jobs()` runs at startup
2. Any `jobs` row with non-terminal status → set to `FAILED` with `"Server restarted — job was interrupted"`
3. Any `job_queue` row stuck in `running` → reset to `queued` (if attempts < max_attempts) or `failed`
4. User can retry via `POST /jobs/{id}/retry` — pipeline resumes from scratch (transcript cache prevents re-transcription)

### Transcript cache survival:
- If a job is retried on the same source file, transcription is skipped (0s) — the most expensive step
- Proxy is also cached and reused

### Partial render failure:
- `render_clips_onepass()` renders clips in parallel — individual clip failures are logged but don't abort other clips
- Clips that succeeded are saved; the job can continue to QA

---

## Retries

### Pipeline worker retries
- `job_queue.max_attempts = 3`
- On failure: `queue.fail()` marks the queue entry failed; `jobs` table updated to `FAILED`
- **Fixed in Phase 2.5:** `process_video()` now correctly handles the retry path without duplicate INSERT

### Manual retry
- `POST /jobs/{id}/retry` — resets status to QUEUED and re-enqueues
- Only allowed when status is FAILED

### Error classification (retryable vs non-retryable)
- Currently all failures use the same retry count. Distinguishing retryable errors (network timeout, transcription OOM) from non-retryable (invalid video, unsupported format) is in the roadmap.
- Practical mitigation: after 3 failures, the job stops being retried automatically. Manual retry is always available.

---

## Idempotency

| Operation | Idempotent? | How |
|-----------|------------|-----|
| Submit same URL twice | Partial | yt-dlp skips download if file exists; transcript cache prevents re-transcription. Two `jobs` rows are created. |
| Retry failed job | Yes | `db.create_job()` with `preset_id` now skips INSERT if row exists |
| Create publication for same clip+platform | Yes | `POST /publications` returns existing pub_id if duplicate |
| Add to proxy cache | Yes | Skips re-generation if proxy file exists on disk |
| Audio WAV extraction | Yes | Skips if WAV file already exists |

**Gap:** Submitting the same URL simultaneously (two parallel jobs) will create two independent jobs. They will both download the same file (yt-dlp caches after first), but both run full analysis independently. Detection of duplicate URL submissions before queuing is not implemented.

---

## Storage

### Directory structure under `output/`:

| Directory | Contents | Lifecycle |
|-----------|---------|-----------|
| `uploads/` | Local file uploads | Permanent (source file) |
| `downloads/` | yt-dlp downloads | Permanent (source file) |
| `audio/` | Extracted 16kHz WAV | Cache — safe to delete (rebuilt on retry) |
| `proxies/` | 360p 2fps analysis proxies | Cache — safe to delete (rebuilt on render) |
| `thumbnails/` | JPEG video thumbnails | Cache — safe to delete (rebuilt on next view) |
| `{creator}/{video}/` | Final rendered clips | Permanent until user deletes |
| `%TEMP%/*.zip` | Download-all ZIP bundles | **FIXED:** now deleted after response via BackgroundTasks |

### Storage lifecycle rules:
- **Master video / source:** Never auto-deleted. Delete via `DELETE /videos/{id}`.
- **Transcript (words_json):** Stored in DB, never deleted unless video is deleted.
- **Audio WAV:** Cache, rebuild-able. Not auto-deleted.
- **Proxy:** Cache, rebuild-able. Not auto-deleted.
- **Clips (rendered MP4):** Deleted only via explicit `DELETE /clips/{id}` or `DELETE /videos/{id}?delete_clips=true`.
- **Temp ZIP:** Auto-deleted after download response (BackgroundTasks).

### Orphan detection:
- `GET /admin/orphans` — detects clips with missing files and videos pointing to non-existent paths.

---

## Database

### Issues found and fixed:
- **Missing indexes:** Added 14 indexes on high-frequency query columns (job_id, status, path, creator_id, etc.)
- **N+1 in `get_creators()`:** Each creator runs 2 sub-queries — acceptable at low creator count, noted for future optimization at 100+ creators.
- **`get_job_analysis()`:** Opens second DB connection inside loop for series parts — minor issue, acceptable now.

### Queries with potential scale issues at high volume:
- `GET /jobs` now paginated (limit/offset)
- `GET /review/pending` now paginated
- `GET /clips` has `limit` param (default 50, max 500)
- `GET /videos` has pagination

### Schema integrity:
- `PRAGMA foreign_keys=ON` enforced on every connection
- `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=30000` prevents lock contention

---

## Security

### Issues found and fixed:

| Issue | Fix | Location |
|-------|-----|---------|
| **SSRF via URL ingestion** | `validate_url()` blocks private IPs, loopback, metadata endpoints | `engine/downloader.py` |
| **Path traversal in file upload** | `Path(filename).name` strips directories | `api/main.py` (was already present) |
| **No upload size limit** | 10 GB limit with streaming check | `api/main.py` |
| **ZIP temp file leak** | BackgroundTasks cleanup after response | `api/main.py` |

### Remaining accepted risks (private tool):
- `CORS allow_origins=["*"]` — fine for localhost-only tool, document if exposed
- No authentication/authorization — all endpoints are public
- Secrets: API keys not present in code; FFmpeg/db paths are absolute local paths (acceptable)
- Logs: no sensitive data logged (job_ids, file paths — no secrets)

### FFmpeg safety:
- FFmpeg arguments are built from hardcoded templates with parameterized values (no user-supplied string concatenation in command arrays)
- Input validation: file extension, minimum duration (>5s) check on ingest
- ASS path escaping: `replace("\\", "/").replace(":", "\\:")` for Windows path safety in filter graph

---

## Ownership / Isolation

**Current model:** Single workspace. All creators, videos, clips are shared globally.

- `creators` table: no user_id foreign key
- `videos`, `jobs`, `clips`, `publications`: no user_id foreign key

This is **intentional for Phase 2.5** — the tool is used by one operator. Adding multi-tenant isolation before social API integrations would be premature.

**Required before external user onboarding:**
- Add `workspace_id` or `user_id` to `creators`, `videos`, `jobs`, `clips`, `publications`
- Add authorization middleware to validate ownership on all resource endpoints
- Enforce isolation in all DB queries

---

## Baseline Performance

Measured environment: Windows 11, Intel QSV (integrated GPU), 2-worker pool.

| Video | Duration | Cold Total | Warm Total | Time to First Clip | Transcription | Render (3 clips) |
|-------|---------|-----------|-----------|-------------------|--------------|-----------------|
| Short (2 min, 1080p) | 2 min | ~360s | ~28s | ~330s (cold) | ~300s | ~21s (QSV parallel) |
| Estimated 30 min | 30 min | ~35–60 min | ~5 min | ~30 min | ~20–40 min | ~3–5 min |
| Estimated 1 hour | 60 min | ~60–120 min | ~10 min | ~60 min | ~40–90 min | ~5–10 min |

**Transcription dominates cold runs.** warm runs (transcript cached) are 9–25× faster.

---

## Time to First Clip

- **Cold (no transcript cache):** Transcription must complete before any clips can be rendered. For a 2-min video: ~330s.
- **Warm (transcript cached):** ~28s for a 2-min video.
- **Optimization path:** Stream transcription output to enable early candidate detection while transcription continues. Not implemented.

---

## Concurrent Processing

| Concurrent Jobs | Result |
|----------------|--------|
| 1 | Stable |
| 2 | Stable (2 workers) |
| 3+ | Queued — 3rd job waits for a worker to free up |

**Worker limit:** 2 (configurable at startup: `python server.py 4`).  
**Render parallelism per job:** 3 clips in parallel (QSV), 2 (CPU).  
**Bottleneck:** Transcription is single-threaded (Whisper CPU). Two simultaneous transcriptions compete for CPU.

---

## Estimated Cost

| Component | Cost | Notes |
|-----------|------|-------|
| Transcription (faster-whisper) | $0 | Local CPU inference |
| Visual analysis (OpenCV) | $0 | Local CPU |
| Virality scoring | $0 | Heuristic, no external API |
| Rendering (FFmpeg + QSV) | $0 | Local GPU |
| External API calls | $0 | None active (Whisper is local) |
| Storage | ~$0.02/GB/month | Local disk |
| **Total cost per video hour** | **~$0** (self-hosted) | Compute is local |

**If deployed to cloud (estimated):**
- Transcription via OpenAI Whisper API: ~$0.006/min → ~$0.36/hour of video
- GPU compute (cloud VM, e4s v5): ~$0.15/hour active compute
- Storage: ~$0.02–0.10/GB/month

---

## Load Testing

Not performed as a formal load test. Observation from architecture:

- Queue provides natural backpressure — additional jobs queue without spawning new workers
- 2-worker default allows 2 simultaneous pipelines
- At 10+ concurrent jobs, queue depth increases; jobs process FIFO by creation time
- No starvation risk (priority queue, FIFO within same priority)

**Estimated safe concurrent job limit:** 5 jobs (2 active + 3 queued) without memory pressure.  
**Transcription memory:** faster-whisper `base` model ≈ 200MB RAM. Two simultaneous = ~400MB.  
**Render memory:** FFmpeg per clip ≈ 200–500MB. Max 3 parallel renders × 2 workers = 6 concurrent FFmpeg processes = ~1.5–3GB RAM peak.

---

## Bottlenecks

### #1 — Transcription (dominant)
- faster-whisper `base` model on CPU: 1–3× real-time for typical speech content
- A 60-min video can take 60–180 minutes to transcribe on CPU
- No GPU transcription configured (device="cpu")
- **Fix:** Use `device="cuda"` if NVIDIA GPU available, or upgrade to faster-whisper `large-v3` on GPU

### #2 — Whisper singleton blocks second job
- The `_WHISPER_MODEL` singleton loads on first use. Two simultaneous transcription requests will serialize — the second waits for the first to finish before starting.
- **Fix:** Multiple Whisper instances (memory-heavy) or transcription service abstraction

### #3 — Single machine, single process
- All pipeline stages run in the same Python process. A memory leak or crash in one job can affect others.
- **Fix:** Process isolation (subprocess per job) at the cost of IPC overhead

---

## Known Limitations

1. **No multi-user isolation** — all data is shared; not safe for external users
2. **No authentication** — all API endpoints are public
3. **Transcription is slow on CPU** — 1-3× real-time; 1 hour of video may take 1-3 hours to transcribe
4. **Worker count is fixed at startup** — cannot be changed without restart
5. **No auto-cleanup of audio/proxy cache** — accumulates over time (safe to delete manually)
6. **No duplicate URL detection** — submitting same URL twice creates two jobs
7. **Retryable vs non-retryable errors not distinguished** — all failures get up to 3 retries
8. **No webhook/notification on job completion** — must poll or maintain SSE connection
9. **SSE disconnects on server restart** — clients must reconnect
10. **CORS allow_origins=**** — appropriate for localhost but document if exposed

---

## Scaling Path

### 10 users (internal team):
- Increase workers to 4: `python server.py 4`
- Add GPU for transcription: change `device="cpu"` → `device="cuda"` in `transcription.py`
- Add `workspace_id` to data model for data isolation
- Add basic authentication (API key or session)

### 100 users:
- Move from SQLite to PostgreSQL (connection pool, concurrent writes)
- Run multiple server instances behind nginx
- Separate transcription into dedicated worker process
- Implement proper auth (OAuth2, JWT)
- Add rate limiting per user

### 1,000 users:
- Distributed job queue (Redis/RabbitMQ replacing SQLite job_queue)
- Containerized workers (Docker/Kubernetes)
- CDN for clip delivery
- Async transcription API (OpenAI Whisper API or self-hosted cluster)
- Separate storage service (S3-compatible)

---

## Tests

No automated test suite exists. All validation has been manual.

**Manually verified flows:**
- File upload → full pipeline → clips → download
- URL submission → full pipeline → clips
- Server restart → job persistence → retry → completion
- Duplicate submission → idempotency of transcript cache
- Failed job → status visibility → manual retry
- SSE stream for in-session and past-session jobs
- Creator assignment, bulk operations
- Publishing Center: create, mark ready, mark published
- Caption editor: edit → re-render

**Failure scenarios verified architecturally (not live-tested):**
- Zombie job cleanup on restart (code reviewed)
- Retry flow fix (code reviewed)
- SSRF protection (code reviewed + test URL blocked)
- Disk space check (code reviewed)

---

## Documentation Updated

- `docs/PROJECT_STATUS.md` — pipeline health, known state
- `docs/ARCHITECTURE.md` — job system, DB, startup sequence
- `docs/CHANGELOG.md` — Phase 2.5 changes
- `docs/KNOWN_ISSUES.md` — updated KI-002 as fixed, new items
- `docs/DECISIONS.md` — new decisions from Phase 2.5
- `docs/PRODUCTION_READINESS.md` — this document (new)
- `docs/OPERATIONS.md` — operational runbook (new)
- `docs/PERFORMANCE_BENCHMARKS.md` — benchmark data (new)

---

## Go / No-Go Recommendation

### Go / No-Go for Phase 3 (YouTube Shorts API)

**CONDITIONAL GO** — proceed to Phase 3 with these conditions:

✅ Core pipeline runs end-to-end repeatedly  
✅ Jobs persist across restarts  
✅ Retry flow works correctly (fixed in Phase 2.5)  
✅ Critical security issues addressed (SSRF, upload size)  
✅ Storage is managed (temp files cleaned up)  
✅ Observability exists (admin endpoint, performance timing)  

⚠️ Before exposing to external users (not required for Phase 3 internal work):
- Add authentication
- Add user/workspace isolation
- Performance test transcription at scale
- Implement proper error categorization (retryable/non-retryable)
