# Project Status

Last updated: 2026-09-15 (Full-app audit: security, UX, code cleanup)

## Readiness classification: INTERNAL ALPHA READY

See `docs/PRODUCTION_READINESS.md` for full assessment.

## Pipeline health

| Step | Status | Notes |
|------|--------|-------|
| INGEST (URL) | ✓ Working | yt-dlp, auto-detects platform and creator |
| INGEST (local upload) | ✓ Working | Saves as `{job_id}_{original_filename}.mp4`, extracts real title |
| TRANSCRIPTION | ✓ Working | faster-whisper "small" model + VAD filter; openai-whisper fallback; video-only files skip gracefully |
| CANDIDATE DETECTION | ✓ Working | Dual-pass (sentence-peak + sliding-window); intro/outro skip zones; min composite gate (15.0); position-based fallback for no-audio |
| VISUAL ANALYSIS | ✓ Working | Shot detection, motion, face presence |
| AUDIO ANALYSIS | ✓ Working | Skipped for video-only files |
| PLATFORM FIT | ✓ Working | Scores per platform (TikTok, Instagram, YouTube) |
| VIRALITY SCORING | ✓ Working | 9-component heuristic + optional LLM (claude-haiku) via ANTHROPIC_API_KEY; LLM contributes 30% weight when enabled |
| SERIES DETECTION | ✓ Working | Groups candidates into narrative arcs, splits into 2-4 ~30s parts |
| SKILLS | ✓ Working | hook_analyzer, virality_predictor logged to skill_runs |
| CLIP GENERATION | ✓ Working | ffmpeg cut, exact timestamps |
| REFRAME 9:16 | ✓ Working | Smart crop to vertical, 1080×1920 |
| CAPTION BURN-IN | ✓ Working | ASS format, word-level karaoke highlight, 3 presets |
| QA/GATE | ✓ Working | FAIL CLOSED: technical_qa=FAIL or visual_qa=FAIL → REJECT; technical_qa now set from actual file probe |

## Dashboard features

| Feature | Status | Notes |
|---------|--------|-------|
| Library (job list) | ✓ Working | Grouped by creator/video, persists across restarts |
| Clip modal + video player | ✓ Working | Inline playback via `/clips/{id}/preview` |
| Caption editor | ✓ Working | 3 tabs: Style / Words / Position; canvas real-time preview |
| Caption presets | ✓ Working | Impact, Aura, Glowing Bold, Minimal |
| Re-render captions | ✓ Working | POST `/clips/{id}/re-render` |
| Download single clip | ✓ Working | Prefers captioned_path, falls back to output_path |
| Download all (ZIP) | ✓ Working | GET `/jobs/{id}/download-all` |
| SSE job progress | ✓ Working | GET `/jobs/{id}/events` |
| Analysis tab | ✓ Working | Job selector, viral ranking, score tiers, reason tags, series cards, generate actions |
| Generate top clips | ✓ Working | POST `/jobs/{id}/generate-top?n=N` — renders N highest-virality ungenerated candidates |
| Generate series | ✓ Working | POST `/jobs/{id}/generate-series/{series_id}` — renders all parts of a narrative series |
| Publishing Center | ✓ Working | Full manual publishing workflow: create publications, edit metadata, mark ready, mark published, record external URL, bulk actions, download ZIP, manual metrics entry, series order warning |
| Add to Publishing (clip modal) | ✓ Working | Platform selector + "Add to Publishing Center" button in clip player; also "+ Publish" on each clip card in Library views |
| Clip delete | ✓ Working | DELETE /clips/{id} — removes rendered files, captions, publication drafts; available per-clip in Library clip list views |
| Bulk approve/reject clips | ✓ Working | Review tab Select mode — checkboxes + bulk bar; calls /review/{id}/approve|reject in parallel |
| Date display on video cards | ✓ Working | created_at (YYYY-MM-DD) shown in Library video card metadata |
| Date filter: 90d + custom range | ✓ Working | Filter chip panel now includes Last 90 Days and Custom Range (from/to date pickers) |
| Performance metrics entry | ✓ Working | POST /publications/{id}/metrics — manual views/likes/comments/shares entry from Mark Published modal and edit modal |
| Performance timing | ✓ Working | `GET /jobs/{id}/timing`, `GET /performance/summary` — per-stage wall-clock data persisted in `pipeline_timings` |
| Quality evaluation | ✓ Working | Eval tab in clip modal: 3-state decision, 8 reason toggles, correction notes, start/pause timer, save. Missed moments sub-section. Export JSON/CSV. `eval_mode` bypass for re-experiments. |

## Performance (2026-09-10 optimization)

| Optimization | Impact |
|---|---|
| One-pass render (trim+crop+caption = 1 FFmpeg call) | ~3–7× faster rendering |
| Hardware encoding (QSV detected, NVENC fallback) | Additional encode speedup |
| Parallel visual + audio analysis | ~2× faster analysis |
| Proxy video (360p 2fps) for visual analysis | ~3–4× faster visual |
| Transcript cache (path-based) | 0s on re-submission |
| Whisper model singleton | Avoids reload between jobs |
| Audio WAV reuse | Skips re-extraction on retry |

**Benchmarked: 2-min 1920×1080 video, 3 clips, Intel QSV**
- Cold run (no cache): ~360s (transcription dominates)
- Warm run (transcript cached): **28s**
- Render-only (3 clips, one-pass QSV, parallel): **21s**

## Inactive / out of scope

| Feature | Status | Notes |
|---------|--------|-------|
| Social publishing | Stub only | TikTok/Instagram/YouTube adapters exist, OAuth not set up |
| Analytics collection | Stub only | Code exists, never triggered |
| Learning / autopsy | Stub only | Needs published posts with real engagement data |

## Phase 2.5 fixes (2026-09-10)

| Fix | Impact |
|-----|--------|
| Retry flow fixed (duplicate INSERT) | Manual retries now work correctly |
| Zombie job_queue reset on restart | In-flight jobs re-queue after restart |
| Worker updates jobs table on any failure | Status always consistent after crash |
| 14 DB indexes added | Query performance at scale |
| SSRF protection for URL ingestion | Security: blocks internal network access |
| 10 GB file upload limit | Security: prevents disk-fill attacks |
| ZIP temp files cleaned up (KI-002 fixed) | Storage: no more orphaned temp files |
| Disk space check before render | Reliability: fail fast vs mid-render crash |
| /jobs and /review/pending paginated | Scale: no full-table scan on large libraries |
| /health — real component checks | Observability: DB, FFmpeg, workers, disk |
| Environment validation at startup | Reliability: fail fast if FFmpeg missing |
| GET /admin/status — operational snapshot | Observability: queue, errors, storage, perf |
| GET /admin/orphans — file/DB sync check | Storage: detect missing files |

## Worker pool

- 2 daemon threads polling `job_queue` table every 2 seconds (configurable: `python server.py N`)
- Max 3 retry attempts per job
- Zombie cleanup on startup: resets interrupted jobs + stuck queue entries
- `GET /workers/stats` returns live queue counts
- `GET /admin/status` returns full operational snapshot

## Library → Generate Clips architecture (2026-09-10)

**Decision: OPTION A — Library stays in Library; single canonical pipeline.**

- Library = organize, view, filter, manage (no duplicate pipeline)
- Create Clips (+ New Job tab) = the one generation entry point
- "Clips (N)" button on video cards opens `showVideoClips()` — shows clips in Library context without navigating away
- "Generate" button (COMPLETED video, 0 clips) shortcuts to Analysis tab with job preselected
- "Analyze ↗" button in clip list view shortcuts to Analysis for the same job
- No orphan "Generate Clips" button that confuses the canonical flow

**Changes:**
- `renderVideoCards` — new button set: Clips(N) / Generate / Open / Delete
- `showVideoClips(jobId, title)` — new function; loads `/clips?job_id=X` in Library context
- Nav index bug fixed in 3 locations (was pointing to Publishing tab instead of + New Job)
- `openVideoJobs(jobId)` — preselects job in Analysis tab (existing function, unchanged)

## Bugs fixed in 2026-09-10 Phase 1+2 audit

- Delete confirmation dialog was generic — now shows accurate cascade: video records, source files, all clips, rendered files, captions, publication drafts
- Per-clip Delete button missing in Library clip views — now present in `showVideoClips` and `showCreatorClips`
- `DELETE /clips/{id}` endpoint missing — added with full cascade (publications, files, prepublish_decisions)
- `POST /clips/bulk-delete` endpoint missing — added
- `POST /publications/{id}/metrics` endpoint missing — added for manual metric entry
- Mark Published modal had no metrics entry or series warning — both added
- Edit modal had no Regen Metadata button — added (calls `POST /clips/{id}/generate-metadata`)
- Edit modal had no metrics section for published pubs — added

## Bugs fixed in 2026-09-10 functional audit

- `doAssignCreator` assign-modal bug — `_assignTargets` cleared before API call (same pattern as delete button bug)
- `showCreatorClips` filtered by job creator_id (broken for manually-reassigned videos) — now uses `/clips?creator_id=`
- `generateSingleCandidate` ignored candidateId arg — now passes `candidate_id` param to `generate-top`
- Unassigned sidebar count showed `…` — now shows actual count

## Bugs fixed in 2026-09-09 audit

- AUTO mode (clips=0) produced 0 clips — fixed in `engine/pipeline.py`
- File upload ignored clips/platforms/mode/creator settings — fixed in `dashboard/index.html`
- Zombie job cleanup on startup — now implemented in `workers/pipeline_worker.py`
- SSE stream worked only for in-session jobs — fixed in `api/main.py`
- creator_slug missing from `/clips` endpoint — fixed via videos JOIN
- Job status chip unstyled for past sessions — normalized to lowercase in `list_jobs()`
- Platform fit scores unused in virality scoring — fixed in `engine/analyzers/virality_scorer.py`
- Path traversal in file upload — sanitized filename with `Path().name`
- submitJob() silently swallowed API errors — fixed with proper `resp.ok` check

## Known-good environment

- Python 3.11+
- ffmpeg and ffprobe set in `engine/config.py` (absolute paths)
- faster-whisper 1.2.1 installed
- yt-dlp installed (for URL downloads)
- SQLite WAL at `db/engine.sqlite`
