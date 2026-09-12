# ContentEngine — Claude Context

## What this project is

AI Short-Form Content Engine: a private tool that ingests long-form videos (URL or local upload), runs a 12-step pipeline, and outputs captioned 9:16 clips ready for review. Not a public product.

## Start the server

```powershell
cd C:\Users\edupo\Desktop\ContentEngine
python server.py
# → http://localhost:8000/dashboard
```

## Core rule: preserve what works

**Never delete, rewrite, or refactor working code unless it directly blocks the pipeline.**

The pipeline is: VIDEO → INGEST → PROXY(360p) → TRANSCRIPTION → CANDIDATE DETECTION → VISUAL+AUDIO(parallel) → PLATFORM FIT → VIRALITY SCORING → SKILLS → RENDER(1-pass: trim+crop+caption) → QA/GATE → CLIPS READY

Note: Steps 9–11 (clip generation, reframe, caption burn) are now a **single FFmpeg call** per clip via `engine/renderers/render_clip.py`. `engine/renderers/clip_generator.py`, `reframer.py`, and `caption_burner.py` still exist and still work (used by the re-render endpoint). Do not delete them.

If a bug is not in that path, document it in `docs/KNOWN_ISSUES.md` and move on.

## What to ignore

- Social publishing (TikTok API, Instagram API, YouTube API) — code exists but is not in use. Do not touch.
- Analytics collection (`analytics/collector.py`) — stub, not active.
- Learning/autopsy (`learning/autopsy.py`) — stub, not active.
- Rights check — `rights_verified` is always set to 1 on create. Do not re-add any rights gate.
- OAuth flows — present in API, never used.

## Key decisions (see docs/DECISIONS.md for full rationale)

- SQLite WAL mode is the only DB. No Postgres, no Redis.
- `job_id` is unified: the same UUID goes into `_jobs` dict AND the `jobs` table. Never generate two IDs for one job.
- `/jobs` reads from DB first (persistent), then overlays live in-memory data. Never read only from `_jobs`.
- `_has_audio_stream()` runs before any ffmpeg audio extraction — video-only files are handled with position-based scoring.
- QA gate is FAIL CLOSED: `technical_qa=FAIL` OR `visual_qa=FAIL` → clip is REJECTED.
- Caption system uses ASS format (not SRT). Word-level events, karaoke-style per-word highlight.
- ASS color format: `&HAABBGGRR` (inverted alpha, BGR byte order). Not ARGB.
- Transcript cache is **path-based**: `videos.words_json` reused across jobs that process the same file.
- Visual analysis uses a **360p 2fps proxy** (`videos.proxy_path`), opened once for all candidates.
- Rendering is **one FFmpeg pass**: trim + crop/scale + ASS caption burn combined into a single call.
- Hardware encoding: `engine/hw_accel.detect_encoder()` auto-detects QSV/NVENC; falls back to libx264 veryfast.

## File map (fast orientation)

```
server.py                    — entrypoint: init_db + WorkerPool + uvicorn
engine/config.py             — CONFIG singleton, all paths and thresholds
engine/pipeline.py           — process_video(): 12-step pipeline with PipelineTimer
engine/timing.py             — PipelineTimer: per-stage wall-clock tracking + report
engine/hw_accel.py           — detect_encoder(): NVENC→QSV→libx264 veryfast, lru_cached
engine/proxy.py              — generate_proxy(): 360p 2fps analysis proxy, cached by path
engine/database.py           — init_db(), all CRUD helpers, context manager db()
engine/downloader.py         — yt-dlp wrapper, is_url()
engine/transcription.py      — faster-whisper (singleton model), path-based transcript cache
engine/analyzers/            — candidate_detector, hook_analyzer, virality_predictor, visual_analyzer (proxy+single-open), audio_analyzer
engine/renderers/            — clip_generator, reframer, caption_burner (still used by re-render)
engine/renderers/render_clip.py — ONE-PASS renderer: trim+crop+caption in single FFmpeg call, parallel
engine/captions/             — presets.py, extractor.py, renderer.py (ASS builder + ffmpeg burn)
api/main.py                  — FastAPI app, all REST endpoints
workers/pipeline_worker.py   — WorkerPool + PipelineWorker (2 daemon threads)
workers/job_queue.py         — SQLite-backed job queue (Redis-compatible interface)
publishers/                  — BasePublisher + TikTok/Instagram/YouTube adapters (inactive)
analytics/collector.py       — post-publish metrics (inactive)
learning/autopsy.py          — score vs engagement correlation (inactive)
dashboard/index.html         — SPA dashboard (dark mode, Library + clip modal + caption editor)
db/engine.sqlite             — persistent state, WAL mode
```

## Database tables

`jobs`, `videos`, `candidates`, `clips`, `skill_runs`, `prepublish_decisions`, `publish_log`, `post_metrics`, `performance_benchmarks`, `job_queue`, `weight_history`, `autopsy_reports`

Key columns added via `_add_column_if_missing`:
- `clips.caption_data TEXT` — JSON: `{words, has_audio, clip_start, clip_end}`
- `clips.caption_settings TEXT` — JSON preset settings dict
- `clips.review_notes TEXT`
- `videos.creator_slug`, `video_slug`, `source_url`, `source_platform`, `source_title`
- `videos.words_json TEXT` — cached word-level transcript (path-based cache)
- `videos.proxy_path TEXT` — path to 360p 2fps analysis proxy

New table: `pipeline_timings` — per-stage wall-clock data for every job. Query via `GET /jobs/{id}/timing` or `GET /performance/summary`.

## Updating these docs

After every significant change, update:
- `docs/CHANGELOG.md` — what changed and why
- `docs/PROJECT_STATUS.md` — current pipeline state and what's working
- `docs/KNOWN_ISSUES.md` — if a new bug is found but not fixed
- `docs/DECISIONS.md` — if a non-obvious technical choice was made

Update `docs/ROADMAP.md` only when priorities shift.

## Skills workflow

Project skills live in `.claude/skills/`. Full documentation: `docs/CLAUDE_SKILLS.md`.

**After feature additions:** use `clipper-qa`  
**After frontend changes (layout, modals, CSS):** use `frontend-visual-qa`  
**After URL ingestion, file upload, FFmpeg, auth, or storage changes:** use `video-security`  
**Before milestone releases or before exposing to new users:** use `production-readiness`  
**After Library UX changes (filters, bulk actions, collections):** use `library-ux`  
**When adding dependencies or before production milestones:** use `secure-dependencies`  
**When clip quality degrades or after pipeline changes:** use `clipping-engine`

Do not run all skills after every change — each skill has a defined trigger context.
