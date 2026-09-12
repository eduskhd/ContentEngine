# Architecture

## System overview

```
Browser (dashboard/index.html)
        │  REST + SSE
        ▼
FastAPI app  (api/main.py)  ← port 8000, uvicorn
        │
        ├── BackgroundTasks.add_task(_run_job)
        │         └── asyncio.to_thread(process_video)  ← engine/pipeline.py
        │
        └── WorkerPool  (workers/pipeline_worker.py)
                  └── 2 PipelineWorker threads
                            └── poll job_queue table → process_video
```

## Startup sequence (`server.py`)

1. `dbmod.init_db()` — creates all tables, adds missing columns via `_add_column_if_missing`
2. `WorkerPool(2)` — creates 2 daemon threads (not started yet)
3. Inject pool into `api.main` module (`api_module.pool = pool`)
4. `uvicorn.run(app, host="0.0.0.0", port=8000)` — FastAPI startup event calls `pool.start()`

## Pipeline (`engine/pipeline.py` → `process_video()`)

```
Step  1  INGEST         yt-dlp (URL) or direct copy (local)
                        → produces video file + download_meta
Step  2  PROBE          ffprobe for duration/fps/width/height
                        → create_video() in DB (rights_verified=1 always)
Step  3  TRANSCRIPTION  _has_audio_stream() check first
                        → faster-whisper → word list with timestamps
                        → video-only: returns [] words, skip to step 4
Step  4  CANDIDATES     sliding window (min/max_clip_duration from config)
                        → semantic + hook + pace scoring per window
                        → no-audio fallback: position-based scoring (30–50 pts)
Step  5  VISUAL         shot boundary, motion intensity, face presence
Step  6  AUDIO          loudness, music detection (skipped if no audio)
Step  7  PLATFORM FIT   per-platform score: TikTok/Instagram/YouTube ratios
Step  8  VIRALITY       ensemble: virality_predictor*w + hook*w + visual*w + audio*w
                        → AUTO mode: threshold 40.0, filters candidates
Step  9  SKILLS         hook_analyzer + virality_predictor logged to skill_runs
Step 10  CLIP GEN       ffmpeg -ss {start} -t {dur} -c copy
Step 11  REFRAME        ffmpeg crop+scale to 1080×1920 (smart center or face-aware)
Step 12  CAPTION BURN   extract_clip_words → ASS file → ffmpeg ass= filter
         QA GATE        technical_qa + visual_qa → PUBLISH or REJECT (FAIL CLOSED)
```

## Job ID unification

API creates `job_id = str(uuid.uuid4())` before calling `process_video`. That same UUID is passed as `job_id=` kwarg and used in `db.create_job()`. The in-memory `_jobs[job_id]` dict and the DB `jobs` row share the same key. `/jobs` reads DB rows first, then overlays live `_jobs` data.

## Database (`db/engine.sqlite`, WAL mode)

```
jobs                  — top-level job record (status, mode, creator)
videos                — one per job; duration, fps, transcript, slugs
candidates            — N per video; scored windows
clips                 — N per video; output_path, captioned_path, qa results
skill_runs            — per-skill execution log
prepublish_decisions  — gate decision record per clip
publish_log           — post publish record (platform, post_id, url)
post_metrics          — engagement metrics (inactive)
performance_benchmarks — percentile thresholds (inactive)
job_queue             — SQLite-backed work queue (Redis-compatible)
weight_history        — scoring weight change log
autopsy_reports       — correlation reports (inactive)
```

All connections use `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`. Context manager `db()` auto-commits or rolls back.

## Caption system (`engine/captions/`)

```
presets.py    — 3 presets: impact / aura / glowing_bold
               get_preset(name), list_presets(), default_settings(), apply_overrides()

extractor.py  — extract_clip_words(all_words, clip_start, clip_end)
                  normalizes timestamps to t=0 within the clip
               group_words(words, max_words=4)
                  groups into [{words, start, end, text}]
                  breaks on punctuation: . , ! ? ; :

renderer.py   — build_ass(words, settings, width, height) → ASS string
                  karaoke: per-word events, highlight color + scale override
                  _hex_to_ass(hex_color) → &HAABBGGRR (BGR, inverted alpha)
               burn_captions_ass(input, output, words, settings, w, h) → bool
                  writes temp .ass file, ffmpeg -vf "ass='path'"
                  falls back to shutil.copy2 when no words or enabled=False
```

Caption data is stored as JSON in `clips.caption_data` and `clips.caption_settings`. Re-render hits `POST /clips/{id}/re-render`.

## Publishers (inactive)

`publishers/__init__.py` → `get_publisher(platform)` factory. Adapters: TikTokPublisher, InstagramPublisher, YouTubePublisher (all extend `BasePublisher`). Publishing only activates when `CONFIG.mode == "AUTO"`, `rights_verified=1`, and `prepublish_decision == "PUBLISH"`.

## Worker queue

`workers/job_queue.py` — `JobQueue` class backed by `job_queue` SQLite table. Interface is Redis-compatible (enqueue/dequeue/complete/fail/status/stats). Index on `(status, priority DESC, created_at ASC)` for efficient dequeue. Max 3 retry attempts.

## Config (`engine/config.py`)

Single `CONFIG` singleton. Key settings:
- `ffmpeg_path`, `ffprobe_path` — set to `"ffmpeg"` / `"ffprobe"` (must be on PATH)
- `output_dir` — where clips land
- `db_path` — `db/engine.sqlite`
- `mode` — `"REVIEW"` (default) or `"AUTO"` (enables publishing)
- `min_clip_duration`, `max_clip_duration` — candidate window range
- `virality_ensemble` — `ScoringWeights` dataclass with per-signal weights
