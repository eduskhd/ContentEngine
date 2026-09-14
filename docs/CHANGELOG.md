# Changelog

## 2026-09-14 — Sprint B/C: 8 feature improvements

### B-002 — Spanish content scoring
- `engine/analyzers/semantic_analyzer.py`: `_detect_language()` uses Spanish function-word frequency (12% threshold) to auto-detect Spanish transcripts. Full Spanish word banks added (`HOOK_PHRASES_ES`, `EMOTION_WORDS_ES`, `CONFLICT_WORDS_ES`, story structure, payoff, cliffhanger, educational, personal narrative). `_REASON_TRANSLATIONS_ES` translates all 22 reason strings. `analyze_segment()` selects the appropriate bank per language and returns `"lang"` in the result dict.
- `engine/analyzers/virality_scorer.py`: reads `lang` from `score_breakdown`; all threshold-based reason strings translated via `_VIRALITY_REASON_TRANSLATIONS_ES`. Hook-type labels translated.
- `engine/analyzers/llm_analyzer.py`: system prompt instructs LLM to return `reasons` in Spanish when transcript is Spanish.
- `engine/analyzers/candidate_detector.py`: `lang` field propagated through `score_breakdown`.

### B-003 — Dashboard LLM indicator
- `GET /health` now includes `llm_enabled: bool`. Dashboard shows "✦ LLM ON" (green) or "LLM OFF" (gray) badge next to mode indicator.

### B-004 — Retranscribe endpoint
- `POST /clips/{id}/retranscribe`: rebuilds `caption_data` for a clip from the video's transcript cache using `extract_clip_words()`. Falls back to re-running Whisper if `words_json` cache is missing. Fixes clips created before the caption_data feature was added.

### B-005 — Permanent error classification
- `workers/pipeline_worker.py`: `_classify_pipeline_error()` classifies errors as RETRYABLE (network, OOM) or PERMANENT (invalid format, codec errors). PERMANENT errors written to `jobs.error_category`. `_cleanup_zombie_jobs()` skips re-queuing jobs with `error_category=PERMANENT`, preventing retry loops on invalid input files.
- `engine/database.py`: `jobs.error_category TEXT` column added; `update_job()` accepts `error_category` kwarg.

### C-001 — URL deduplication
- `POST /jobs/from-url`: returns existing non-failed job with `{job_id, status, duplicate: true}` if same URL already queued/processed.

### C-002 — SQL column allowlists
- `update_video`, `update_candidate`, `update_clip`, `update_creator`, `update_publication` in `engine/database.py` now validate kwargs against frozenset allowlists, raising `ValueError` on unknown columns.

### C-004 — Minimal caption preset
- `engine/captions/presets.py`: `"minimal"` preset added (white text, semi-transparent background, no glow, no uppercase, fade animation, 5 words/group). Suitable for corporate or educational content.

### C-005 — LLM token cost logging
- `engine/analyzers/llm_analyzer.py`: thread-safe per-job token usage accumulator; `pop_llm_usage(job_id)` returns `{llm_tokens_used, llm_cost_usd}`. Pricing: $0.80/1M input, $4.00/1M output (claude-haiku-4-5 estimate).
- `engine/pipeline.py`: reads LLM usage after virality_scoring and passes to timer stage meta.
- `engine/timing.py`: `to_rows()` extracts `llm_tokens_used`/`llm_cost_usd` as top-level keys.
- `engine/database.py`: `pipeline_timings.llm_tokens_used INT`, `pipeline_timings.llm_cost_usd REAL` columns added. Visible via `GET /jobs/{id}/timing`.

## 2026-09-14 — Security Audit: 7 fixes applied

### Networking
- **Host binding hardened:** `server.py` now binds to `127.0.0.1` instead of `0.0.0.0`. The server is no longer reachable from other devices on the same LAN.
- **CORS restricted:** `allow_origins=["*"]` replaced with explicit localhost origins (`http://localhost:8000`, `http://127.0.0.1:8000`). Wildcard allowed any website to call the API cross-origin.

### File Upload
- **Magic-bytes validation added to `POST /jobs`:** Uploaded files are now checked against known video container signatures (MP4/ftyp, MKV/WebM, AVI, OGG, MPEG). Non-video files are rejected with HTTP 415 and the partial upload is deleted. Previously only file size was checked.

### Dashboard XSS (7 vector fixes)
- **`_esc()` strengthened:** Now escapes `>` and `'` in addition to `&`, `<`, `"` — prevents attribute breakout via apostrophe and unescaped close-bracket.
- **Jobs table `src`/`srcDisplay`:** Source URL was embedded raw into `title=""` attribute and cell text. Both now pass through `_esc()`.
- **Error message `e.message`:** API error messages were injected into `innerHTML` unescaped. Now escaped.
- **Video card `platform` field:** `source_platform` was embedded into `innerHTML` without escaping. Now escaped.

### Findings NOT fixed — see pending section in audit report

## 2026-09-12 — Platform Audit: Dashboard + DB Fixes

### Dashboard (dashboard/index.html)
- **Error handling:** `reviewAction()` and `modalAction()` now wrapped in try/catch — approval failures show an error toast instead of silently doing nothing
- **Bulk approve/reject:** Review tab now has Select mode — checkbox per clip, "Approve Selected" / "Reject Selected" bulk bar, same UX pattern as Library bulk actions
- **Date on video cards:** `created_at` (YYYY-MM-DD) now visible in video card metadata row in Library views
- **Date filter expanded:** Added "Last 90 days" and "Custom Range" options to the date filter chip panel; custom range shows from/to date pickers
- **Analytics stubs fixed:** "Collect metrics now" and "Run content autopsy" buttons no longer show fake "success" — they explain what's needed to activate the feature
- **Clip created_at in review:** Review cards now show clip creation date

### Database (engine/database.py)
- **FK cascade fix:** `_delete_video_cascade()` now checks remaining videos for the job before deleting the job record — previously, two videos sharing the same `job_id` caused the second deletion to fail with `FOREIGN KEY constraint failed`, silently rolling back the transaction (KI-012)

### Data
- All 20 test videos, clips, jobs, candidates, and related records purged
- 15 creators preserved

## 2026-09-12 — Clipping Engine V2

### Transcription
- **Model upgrade:** `whisper_model = "small"` (was "base") — better word-level timestamps (~40-50% slower cold, same warm cache hit)
- **VAD filter:** `vad_filter=True` added to faster-whisper call — removes silence segments, reduces hallucinations on noisy audio; graceful fallback on older faster-whisper versions

### Candidate Detection
- **Intro/outro skip zones:** Candidates from first 3% or last 3% of video are discarded (`intro_skip_ratio=0.03`, `outro_skip_ratio=0.03`) — prevents title cards and CTAs from becoming clips
- **Minimum composite score gate:** Candidates scoring below 15.0 composite are dropped before DB persist (`min_candidate_composite=15.0`)
- **Sliding window unified:** smart-cut window in sliding-window pass now uses `CONFIG.smart_cut_window` (12s) instead of hardcoded 8s — consistent boundary quality with sentence-peak pass

### Semantic Analysis
- **Hook detection window:** `first_words = w_in[:15]` (was `[:10]`) — catches hook phrases in slower-paced content and podcast-style openings

### Virality Scoring
- **Position bonus bug fix:** `score_virality()` now accepts `video_duration` parameter; position bonus uses actual video duration instead of `cand["end_s"]` — clips in the middle/end of a long video were incorrectly penalized
- Pipeline passes `video_duration=duration_s` to `score_virality`

### Caption Quality
- **Word confidence filter:** `caption_min_word_confidence=0.30` — words with whisper probability < 0.3 are excluded from caption output; prevents garbled/uncertain transcription from appearing on screen

### Auto QA
- **Technical QA now real:** `_check_technical_qa()` helper added to `render_clip.py` — sets `technical_qa=PASS/FAIL` based on actual probe of rendered file; checks file size, video stream presence, duration deviation (>40% = FAIL), fps ≥ 10; was always "PENDING" before
- **QA notes:** `qa_notes` column now stores structured dict with error or warning details

### New Skill
- **`/clipping-engine`:** Project skill added at `.claude/skills/clipping-engine/SKILL.md` — structured audit and improvement guide for the clipping pipeline

## 2026-09-11 — Viral Detection v2

### New: LLM-based viral analysis (`engine/analyzers/llm_analyzer.py`)
- New module: `analyze_candidates_llm()` — calls Claude claude-haiku-4-5-20251001 API to score candidates
- Scores: viral_potential, hook_quality, emotional_resonance, shareability, standalone_value, narrative_completeness, hook_type
- Batches up to 8 candidates per API call for efficiency (~$0.004/batch, ~$0.012/video)
- Results cached in `candidates.score_breakdown['llm_analysis']` — not re-called on retry
- Gracefully disabled when `ANTHROPIC_API_KEY` is not set (heuristic-only mode)
- To enable: set `ANTHROPIC_API_KEY` environment variable before starting server

### Virality scorer: LLM blending (`engine/analyzers/virality_scorer.py`)
- When LLM scores available, uses blended weight scheme: LLM 30%, heuristic components 70%
- LLM-enhanced components: hook_quality, emotional_resonance, standalone_value, shareability (60/40 LLM/heuristic blend)
- New fields in scored results: `llm_scored` (bool), `hook_type` (string label)
- Reasons list now prioritizes LLM-generated reasons (more specific than word-bank reasons)
- Hook type label added: "Shock/surprise hook", "Question-based hook", "Comedy hook", etc.
- cliffhanger signal now contributes to payoff_strength

### Semantic analyzer: 3× expanded word banks (`engine/analyzers/semantic_analyzer.py`)
- HOOK_PHRASES: 38 → 90+ patterns (educational, personal story, question-based, controversy hooks)
- EMOTION_WORDS: 8 categories now (added "inspiration", "relatability"); each expanded 2-3×
- New: CLIFFHANGER_WORDS (20 phrases), RHETORICAL_QUESTIONS, PERSONAL_STORY_MARKERS, EDUCATIONAL_MARKERS
- New: STANDALONE_INTRO_PHRASES (better detection of self-contained segment openings)
- New: `content_type` field in analyze_segment() output — classifies segment as hook/conflict/humor/revelation/educational/story/relatable
- Improved: emotion scoring weights high-impact emotions (excitement/tension/anger/sadness/surprise) more than supporting ones
- Improved: retention score adds content_density component and escalation_bonus (rewards second-half interest increase)
- Improved: story_structure now includes `has_cliffhanger` field

### Candidate detector: dual-pass + diversity (`engine/analyzers/candidate_detector.py`)
- New: sliding window pass (35s windows, 50% overlap) runs alongside sentence-peak pass
- Catches "slow burn" story arcs that don't peak on any single sentence
- Adaptive context expansion: higher peak score → more context captured (10–20s back, 8–15s forward)
- New: type-diversity selection — allows at most 2 candidates of the same `content_type`, fills remaining from overflow sorted by score
- Improved: cliffhanger phrases now act as sentence boundary signals in `_segment_sentences()`
- Breakdown now includes: `relatability`, `educational`, `content_type` fields

### Infrastructure
- `requirements.txt`: added `anthropic>=0.40.0`
- `anthropic` package installed (v1.5.0)

---

## 2026-09-10 — Phase 2.5 Production Readiness Gate

### Critical bug fixes

- **Retry flow broken** — `process_video()` called `db.create_job(preset_id=job_id)` which did `INSERT INTO jobs` even on retries when the row already existed. The INSERT failed with UNIQUE constraint, making all manual retries fail silently. Fixed: `create_job()` now checks for existing row when `preset_id` is provided and skips the INSERT. (`engine/database.py`)

- **Zombie job_queue entries not reset on restart** — `_cleanup_zombie_jobs()` reset the `jobs` table but left `job_queue` rows stuck in `status='running'`. Those entries were never retried after a restart. Fixed: on startup, running job_queue entries are reset to `queued` (or `failed` if max_attempts reached). (`workers/pipeline_worker.py`)

- **Worker didn't update jobs table on pre-pipeline failure** — When `process_video()` raised an exception before entering its own try block, the worker updated `_jobs` and `job_queue` but not the `jobs` table. The job remained in QUEUED status in the DB after a restart. Fixed: worker now calls `db.update_job(jid, status="FAILED")` in its exception handler as a safety net. (`workers/pipeline_worker.py`)

### Security fixes

- **SSRF protection for URL ingestion** — Added `validate_url()` to `engine/downloader.py`. Blocks private IP ranges (RFC 1918), loopback, link-local, reserved ranges, and known cloud metadata endpoints (169.254.169.254, metadata.google.internal). Called at the start of `download_url()` and in `POST /jobs/from-url` before queuing. (`engine/downloader.py`, `api/main.py`)

- **File upload size limit** — `POST /jobs` now enforces a 10 GB streaming limit. Oversized uploads are rejected with HTTP 413 and the partial file is deleted. (`api/main.py`)

### Reliability fixes

- **ZIP temp file leak (KI-002) fixed** — `GET /jobs/{id}/download-all` and `GET /publications/download-zip` now delete their temp `.zip` files after the response is sent, using FastAPI `BackgroundTasks`. (`api/main.py`)

- **Disk space check before render** — `render_clips_onepass()` now checks available disk space before starting FFmpeg renders. Fails fast with `STORAGE_INSUFFICIENT` error if < 2 GB free, instead of cryptic mid-render FFmpeg error. (`engine/renderers/render_clip.py`)

### Performance fixes

- **Database indexes added** — 14 indexes added on high-frequency query columns: `candidates(job_id, video_id)`, `clips(job_id, candidate_id)`, `jobs(status, created_at)`, `videos(path, job_id, creator_id)`, `pipeline_timings(job_id)`, `publications(clip_id, status, creator_id)`, `prepublish_decisions(clip_id)`. Added on every `init_db()` call via `CREATE INDEX IF NOT EXISTS`. (`engine/database.py`)

- **Pagination for /jobs and /review/pending** — `GET /jobs` now accepts `limit` (default 100, max 500), `offset`, and `status` query params. `GET /review/pending` now accepts `limit` and `offset`. Prevents full-table scans on large libraries. (`api/main.py`)

### Observability

- **Improved /health endpoint** — Now checks DB connectivity, FFmpeg/FFprobe presence, worker liveness, and disk space. Returns `status: "degraded"` with details when components fail. (`api/main.py`)

- **Environment validation at startup** — `server.py` now validates FFmpeg paths, output directory writability, and disk space before launching uvicorn. Fails fast with clear error messages instead of crashing during the first job. (`server.py`)

- **Admin observability endpoint** — `GET /admin/status` returns operational snapshot: queue stats, worker liveness, last 10 failed jobs, storage usage by category, DB row counts, and average stage times. (`api/main.py`)

- **Orphan detection endpoint** — `GET /admin/orphans` detects clips and videos with DB records pointing to missing files. (`api/main.py`)

### Documentation

- Created `docs/PRODUCTION_READINESS.md` — full Phase 2.5 assessment with classification INTERNAL ALPHA READY
- Created `docs/OPERATIONS.md` — operational runbook (start/stop, recovery, storage management, debugging)
- Created `docs/PERFORMANCE_BENCHMARKS.md` — benchmark data, cost estimates, scaling recommendations
- Updated `docs/KNOWN_ISSUES.md` — KI-002 marked fixed; added KI-007 through KI-010 for known gaps
- Updated `docs/DECISIONS.md` — D-016 through D-020 documenting Phase 2.5 decisions
- Updated `docs/ROADMAP.md` — Phase 2.5 marked done; canonical roadmap added

---

## 2026-09-10 — Phase 1+2 Completeness Audit (Stability, Quality, Publishing Center)

### Bug fixes

- **Delete confirmation dialog** — Now shows accurate cascade info: lists video records, source files, all generated clips, rendered MP4s, captions, and publication drafts. Separates "Videos + Clips" vs "Videos only" actions clearly.
- **Per-clip Delete button** — Added Delete action to every clip card in `showVideoClips()` (Library video → Clips view) and `showCreatorClips()` (Creator detail Clips tab). Each delete prompts with accurate cascade info and removes the card from the DOM on success.

### New API endpoints

- **`DELETE /clips/{clip_id}`** — Deletes a single clip record, rendered files (captioned + output), and all associated publication drafts and prepublish decisions.
- **`POST /clips/bulk-delete`** — Bulk clip deletion by clip_id array. Same cascade as single delete.
- **`POST /publications/{pub_id}/metrics`** — Record manual performance metrics (views, likes, comments, shares, saves, avg_watch_time_s, etc.) for a published publication.

### New DB helper

- **`engine/database.py` — `delete_clip_by_id()`** — Proper cascade: clears `publication_metrics`, `publications`, `prepublish_decisions`, deletes captioned_path and output_path files, then removes the clip row.

### Publishing Center improvements

- **Mark Published modal** — Added initial metrics entry fields (views, likes, comments, shares) sent with the mark-published call. Added series order warning shown when `series_part > 1`.
- **Edit modal — Regen Metadata** — New "↻ Regen Metadata" button calls `POST /clips/{id}/generate-metadata` and refreshes title/caption/hashtags fields without saving.
- **Edit modal — Performance Metrics section** — Shown only when publication is `published`. Allows manual entry of views/likes/comments/shares with "Save Metrics" button.
- **`mark-published` endpoint** — Now accepts and records initial metrics alongside the external URL.

---

## 2026-09-10 — Library Clip Generation Architecture (Generate Clips in Library)

### Decision: OPTION A — Library is view-only; single canonical pipeline

Audited the "Generate Clips" flow within Creator folders in Library. The old buttons were ambiguous: "View Clips" opened the Analysis tab, and COMPLETED videos with 0 clips had no action at all.

**Chosen approach:** Library = organize/view/filter. Create Clips (+ New Job tab) = the one generation entry point. Shortcuts from Library to the Analysis tab are OK as long as they pass real IDs.

### Changes

- **`renderVideoCards` — new semantic button set:**
  - `Clips (N)` — calls `showVideoClips(jobId, title)` when the video has clips (stays in Library)
  - `Generate` — calls `openVideoJobs(jobId)` when COMPLETED but 0 clips (shortcut to Analysis tab with job preselected)
  - `Open` — calls `openVideoJobs(jobId)` for non-COMPLETED jobs
  - `🗑` — delete (always present)
- **`showVideoClips(jobId, title)` — new function:** Loads `/clips?job_id=X&limit=200` and renders clips inline in the Library panel. Includes "← Back" button (calls `reloadCurrentView()`), "Analyze ↗" shortcut to Analysis tab, and empty-state button to "Go to Analysis → Generate Clips".
- **Nav index bug fixed (3 locations):** `+ Add Video` and empty-state "Generate" buttons were pointing to nav index [6] (Publishing) or `last-of-type` (OAuth). Fixed to index [5] (+ New Job upload tab).

### Canonical flow

```
CREATE CONTENT:  + New Job tab → Upload/URL → Pipeline → Clips ready
VIEW IN LIBRARY: Library → Creator → Video → Clips (N) → inline clip list
GENERATE MORE:   Library → Creator → Video (COMPLETED, 0 clips) → Generate → Analysis tab
SHORTCUT:        Library clip list → Analyze ↗ → Analysis tab (same job)
```

No orphan buttons. No duplicate pipeline. One entry point.

---

## 2026-09-10 — Functional Audit + Clip Organization Fixes

### Bug fixes

- **`doAssignCreator` assign-modal bug** — `closeAssignModal()` was called before the API used `_assignTargets`, clearing the array (same pattern as the delete button bug fixed previously). Fixed by capturing `[..._assignTargets]` before closing the modal.
- **`showCreatorClips` broken creator filter** — Was fetching all clips and filtering client-side by matching `job.creator_id` (approximate, didn't account for manually-reassigned videos). Fixed: now calls `/clips?creator_id=<id>` which does a proper JOIN through `candidates → videos`.
- **`generateSingleCandidate` ignored its argument** — The "Generate" button on each analysis clip card called `generate-top?n=1` (top ungenerated globally), ignoring the specific `candidateId`. Fixed: now calls `generate-top?n=1&candidate_id=<id>`.
- **Unassigned sidebar count** — Showed `…` instead of actual count. Fixed: fetches up to 200 videos and shows numeric count.

### Feature improvements

- **`/clips` endpoint** — Added `creator_id` and `job_id` query filters. Creator filter supports `__unassigned__` value. Both filters apply a JOIN through `candidates → videos`. Response now includes `creator_id` and `video_id` fields.
- **`GET /clips/{id}`** — Returns `video_id`, `creator_id`, `creator_slug`, `source_title` via JOIN (was bare clips row only).
- **`POST /jobs/{id}/generate-top`** — Added optional `candidate_id` query param to generate a specific candidate instead of the top-N by score.
- **Clip player modal** — Added "Change Creator" button; fetches `video_id` from the clip and opens the assign-creator modal pre-targeted to that video.
- **Creator clips view** — Shows source video title per clip; adds "+ Publish" button to add clips to Publishing Center directly from the creator clips tab.

---

## 2026-09-10 — Performance Optimization Audit

### New files
- **`engine/timing.py`** — `PipelineTimer` class; tracks wall-clock time per stage; produces formatted report + `to_rows()` for DB persistence.
- **`engine/hw_accel.py`** — Hardware encoder detection: NVENC → QSV → CPU libx264 veryfast. Cached at module level (`@lru_cache`). Returns `(encoder, opts, max_parallel_renders)`.
- **`engine/proxy.py`** — Generates a 360p 2fps analysis proxy via FFmpeg ultrafast. Cached by `video_id` and source path in `videos.proxy_path`.
- **`engine/renderers/render_clip.py`** — **One-pass clip renderer**: trim + crop/scale + ASS caption burn in a single FFmpeg call per clip, rendered in parallel up to `hw_accel.max_parallel_renders`.

### Modified files
- **`engine/pipeline.py`** — Full rewrite of orchestration:
  - Every stage wrapped in `PipelineTimer.start/end`; report printed and saved to `pipeline_timings` table.
  - Step 1.5 added: proxy generation.
  - Steps 4 + 5: visual + audio analysis now run in parallel via `ThreadPoolExecutor(2)`.
  - Steps 9–11 collapsed into single call to `render_clips_onepass()` (was 3 sequential calls to `generate_clips`, `reframe_clips`, `burn_captions`).
  - Return value now includes `timing` dict and `total_time_s`.
- **`engine/transcription.py`**:
  - Whisper model kept as module-level singleton (`_WHISPER_MODEL`); loaded once, reused across jobs.
  - Path-based transcript cache: if a video with the same source path was previously processed, `words_json` is reused instantly (skips audio extraction + transcription).
  - Audio WAV file reuse: `_extract_audio` skips re-extraction if WAV already exists on disk.
- **`engine/analyzers/visual_analyzer.py`**:
  - Now accepts `proxy_path` argument; uses proxy if available.
  - Opens `VideoCapture` **once** for all candidate windows (was: one open + seek per candidate).
- **`engine/database.py`**:
  - New `pipeline_timings` table with per-stage timing records.
  - New columns: `videos.words_json TEXT`, `videos.proxy_path TEXT`.
  - New helpers: `get_cached_words`, `get_cached_words_by_path`, `get_proxy_by_path`, `save_words_cache`, `save_proxy_path`, `save_pipeline_timings`, `get_pipeline_timings`.
- **`api/main.py`**:
  - `POST /jobs/{id}/generate-top` and `POST /jobs/{id}/generate-series/{sid}` now use one-pass renderer and load `words_json` from cache.
  - New endpoints: `GET /jobs/{id}/timing`, `GET /performance/summary`.

### Benchmark results (2-min 1920×1080 video, 3 clips, Intel QSV)

| Stage | Before | After | Delta |
|---|---|---|---|
| Transcript (cold) | ~100–400s | 100–400s | same |
| Transcript (cached) | ~100–400s | **0.0s** | **∞×** |
| Visual analysis | ~15–30s | **5–8s** | **3–4×** |
| Proxy generation | — | 3–5s (once) | — |
| Render 3 clips | ~65–150s | **21s** | **3–7×** |
| Total (cached) | ~250–700s | **28s** | **9–25×** |

### Architecture decisions
- One-pass render is the highest-leverage optimization: eliminates 2 of 3 FFmpeg re-encodes per clip.
- QSV encoder (`h264_qsv`) detected at startup via `@lru_cache`; falls back to `libx264 veryfast` if unavailable.
- Visual analysis proxy (360p 2fps): reduces visual analysis from O(N×seek) to O(1 open + N seek on small file).
- Transcript cache is path-based (not job-id-based) so it survives across job retries and re-submissions of the same file.

## 2026-09-10 — Publishing Center

### Added
- **`publications` table**: id, clip_id, creator_id, video_id, series_id, series_part, platform, status, title, caption, hashtags, platform_overrides, scheduled_at, published_at, external_post_id, external_url, error_message, retry_count, publication_order, notes.
- **`social_accounts` table**: stub for future Creator → Platform account mapping (no tokens stored yet).
- **`publication_metrics` table**: stub for future views/likes/comments/shares/saves/completion_rate per publication.
- **`publication_audit_log` table**: action history per publication (created, metadata_updated, marked_ready, marked_published, deleted).
- New DB helpers: `create_publication`, `get_publications`, `get_publication`, `update_publication`, `delete_publication`, `get_publications_for_clip`, `get_publication_stats`, `log_publication_audit`, `add_publication_metrics`, `generate_clip_metadata` (heuristic title/caption/hashtags from virality_reasons).
- New API endpoints:
  - `GET /publications/stats` — counts by status
  - `GET /publications` — list with filters (status, creator_id, platform, search, sort, series_only, standalone_only)
  - `POST /publications` — create for a clip+platform (auto-deduplicates)
  - `GET /publications/{id}` — detail with clip/candidate/creator/video data
  - `PUT /publications/{id}` — update title, caption, hashtags, notes, platform_overrides, scheduled_at, external_url
  - `DELETE /publications/{id}` — delete publication only (clip untouched)
  - `POST /publications/{id}/mark-ready` — transition to ready (validates clip file exists)
  - `POST /publications/{id}/mark-published` — record manual publication + external URL
  - `POST /publications/{id}/cancel` — cancel a publication
  - `POST /publications/bulk-create` — create for multiple clips × multiple platforms
  - `POST /publications/bulk-action` — bulk mark_ready / mark_published / cancel / delete
  - `GET /publications/download-zip` — ZIP of selected clips with named files (creator-video-platform-score.mp4)
  - `POST /clips/{id}/prepare` — create publications for a clip on chosen platforms
  - `POST /clips/{id}/generate-metadata` — generate suggested title/caption/hashtags
  - `GET /clips/{id}/publications` — list all publications for a clip
- **Publishing tab** in dashboard with:
  - Sidebar navigation: All / Ready / Drafts / Scheduled / Published / Failed / Recommended
  - Live badge counts per status
  - Grid and list view toggle
  - Filters: creator, platform, sort
  - Publication cards: thumbnail, virality score, creator, platform pill with status dot, duration, clip series part badge
  - Edit modal: title/caption/hashtags per publication, copy-to-clipboard buttons (Copy Title, Caption, Hashtags, All), save, mark ready, download MP4, preview, delete publication
  - Mark Published modal: records timestamp + optional external URL
  - Open Published Post link when URL is stored
  - Multi-select mode with bulk bar (Mark Ready / Mark Published / Download ZIP / Delete)
  - "Add to Publishing Center" section in the clip player modal (platform checkboxes + button)
  - Empty state with link to Library

### Architecture decisions
- `platform` is a string enum: `tiktok` | `youtube_shorts` | `instagram_reels` — extensible for future platforms
- `platform_overrides` JSON field allows per-platform title/caption/hashtags overrides without duplicating the publication record
- `social_accounts` table is present but empty — no OAuth flows implemented yet
- `publication_metrics` table is present but empty — no API collection implemented yet
- Status flow: `draft` → `ready` → `published` (manual). `scheduling`, `publishing`, `failed` states reserved for future automation
- Duplicate guard: `POST /publications` returns existing pub_id if clip+platform already exists
- `_can_be_ready()` checks: file on disk, not REJECTED. Processing or missing clips stay as `draft`

## 2026-09-09 — Creator-first Library redesign

### Added
- `creators` table in SQLite: id, name, display_name, handle, avatar_color, platform, channel_url, external_channel_id, is_favorite.
- `creator_id` column on `jobs` and `videos` tables.
- `thumbnail_path` column on `videos` table.
- Migration in `init_db()`: creates Creator records from existing `job.creator` names and links videos automatically.
- New API endpoints:
  - `GET /creators` — list all with stats (video_count, clip_count, last_activity, processing_count)
  - `POST /creators` — create (deduplicates by name COLLATE NOCASE)
  - `GET /creators/{id}` — detail with best_score, avg_score
  - `PUT /creators/{id}` — update fields including is_favorite
  - `DELETE /creators/{id}?action=unassign|delete_all`
  - `GET /videos` — list with filters: creator_id, status, platform, search, sort, limit, offset
  - `PATCH /videos/{id}/creator` — assign/unassign a video to a creator
  - `POST /videos/bulk-assign` — bulk creator assignment
  - `DELETE /videos/{id}?delete_clips=true` — delete video + optional cascade
  - `POST /videos/bulk-delete` — bulk delete with cascade option
  - `GET /videos/{id}/thumbnail` — lazy-generate and serve JPEG thumbnail via ffmpeg
  - `POST /jobs/{id}/retry` — re-queue a FAILED job
- Creator_id inheritance: pipeline now reads `jobs.creator_id` after ingest and assigns it to the video.
- Jobs endpoint now returns `creator_id` and `video_id` fields.
- Library tab completely redesigned:
  - Two-column layout: sidebar + main content area
  - Sidebar: search, nav (All Videos, Processing, Failed), creators list with counts
  - Creators grid view: color-coded avatar cards with stats, favorite star, processing badge
  - Creator detail view: header with stats + Videos/Clips tabs
  - Video cards: thumbnail (lazy-loaded), status chip, virality score, clip count, actions menu
  - Grid/List view toggle
  - Multi-select mode with bulk assign + bulk delete actions
  - Delete flow: confirmation modal with "Videos only" vs "Videos + Clips" options
  - Assign creator modal with search and inline "Create New Creator"
  - Unassigned folder (videos with creator_id IS NULL)
  - Processing and Failed views with retry button
- Upload form: creator selector with search dropdown + inline "Create New Creator" option.
- Creator create/edit modal accessible from sidebar and creator grid.

### Changed
- `jobs` API response now includes `creator_id`, `video_id`.
- `process_video()` now sets `video.creator_id` from `job.creator_id` after ingest.

## 2026-09-09 — Viral analysis layer (phase 1)

### Added
- **`engine/analyzers/semantic_analyzer.py`** — Heuristic semantic analysis (no LLM): word-bank emotion detection (7 categories), hook phrase matching (50+ patterns), conflict/humor/revelation scoring, smart boundary detection using pause size + punctuation + connector-word absence, retention scoring (hook_time, pacing, dead_air, progression)
- **`engine/analyzers/series_detector.py`** — Narrative series detection: clusters candidates within 120s gap, requires ≥60s arc, splits into 2-4 parts ~30s each using smart end boundaries, persists to `clip_series` table
- **`engine/analyzers/candidate_detector.py`** — Semantic-first rewrite: sentence segmentation → semantic scoring → peak detection → context expansion ±15s → smart boundaries → IoU deduplication; position-based fallback for no-audio files unchanged
- **`engine/analyzers/virality_scorer.py`** — 9-component weighted formula: semantic_interest 20% + hook 20% + emotional_intensity 15% + standalone 10% + audio 10% + visual 10% + payoff 5% + shareability 5% + short_form_fit 5%. Outputs virality_score, importance_score, retention_score, virality_reasons, tier label
- **`engine/database.py`** — New `clip_series` table; new candidate columns: emotion_score, retention_score, importance_score, hook_time, virality_reasons, smart_start, smart_end, series_id, series_part; CRUD helpers: `create_series()`, `get_job_series()`
- **`engine/config.py`** — New settings: min_virality_for_auto=70.0, target_series_part_duration=30.0, max_series_parts=4, min_series_total_duration=60.0, generate_series=True, deduplicate_iou_threshold=0.5, smart_cut_window=12.0
- **`engine/pipeline.py`** — Step 7.5: series detection after virality scoring; passes `words` to `score_virality()` for semantic context; returns series_ids + series_detected in stats
- **`api/main.py`** — 4 new endpoints: `GET /jobs/{id}/analysis` (ranked candidates + series), `GET /jobs/{id}/series`, `POST /jobs/{id}/generate-top?n=5`, `POST /jobs/{id}/generate-series/{series_id}`
- **`dashboard/index.html`** — Analysis tab: job selector, stats grid (duration/candidates/high virality/series), bulk generate buttons (Top 3/5/10, Best Series), viral clip cards with score tier coloring and reason tags, series cards with part timeline

### Fixed (same session)
- **Windows encoding crash** — `'charmap' codec` on Rich Console box-drawing chars; forced UTF-8 stdout/stderr in `server.py` before any imports
- **Race condition in job queue** — Two workers dequeuing same job simultaneously; fixed with atomic `UPDATE … RETURNING` in `workers/job_queue.py`
- **Pipeline marked FAILED after successful run** — `_print_summary()` threw encoding error AFTER pipeline completed; moved `update_job(COMPLETED)` to after the try/except on summary

## 2026-09-09 — Full functional audit + bug fixes

### Fixed
- **AUTO mode (clips=0) produced 0 clips** — `scored[:0 * finalist_multiplier]` gave empty finalist list. Now uses `cfg.target_clips` (already set to 20 for AUTO) instead of `number_of_clips`. (`engine/pipeline.py`)
- **File upload ignored clips/platforms/mode/creator** — Dashboard sent these as URL query params but FastAPI `Form()` reads only from multipart body. Fixed: now appended to FormData. (`dashboard/index.html`)
- **KI-001 Zombie jobs** — `WorkerPool.start()` now scans for jobs with non-terminal status and marks them FAILED on startup. (`workers/pipeline_worker.py`)
- **KI-004 SSE for past-session jobs** — `/jobs/{id}/events` returned `{"error":"job not found"}` for completed jobs from previous sessions. Now reads DB and returns a final `completed` or `failed` event immediately. (`api/main.py`)
- **creator_slug missing in /clips response** — Overview table always showed `—` for creator. Added LEFT JOIN to `videos` table in `/clips` endpoint. (`api/main.py`)
- **Job status case mismatch** — DB stores uppercase (`COMPLETED`, `FAILED`); `_jobs` uses lowercase. Chips in Jobs tab had no CSS match for past-session jobs. Now normalized to lowercase at API layer. (`api/main.py`)
- **Platform fit scores unused in virality ensemble** — `virality_scorer.py` hardcoded `platform_fit = 0.65` instead of using the scores computed by `analyze_platform_fit()` in step 6. Now reads `cand["platform_scores"]` and uses the real average. (`engine/analyzers/virality_scorer.py`)
- **Path traversal in file upload** — `video.filename` could contain `../` sequences. Sanitized with `Path(video.filename).name`. (`api/main.py`)
- **submitJob() swallowed API errors** — Non-OK HTTP responses (400/500) from fetch were silently ignored, causing partial UI state. Now checks `resp.ok` before proceeding. (`dashboard/index.html`)

### Updated
- `requirements.txt` — Added `faster-whisper>=1.0.0` and `yt-dlp>=2024.1.0`; removed unused `vosk` and `SpeechRecognition` (never imported in codebase)

## 2026-09-08 — Critical pipeline fixes (database lock + captions)

### Fixed
- **"database is locked" crash** — All SQLite connections now use `timeout=30` + `PRAGMA busy_timeout=30000`. Affected `engine/database.py`, `analytics/collector.py`, `learning/autopsy.py`, `workers/job_queue.py`
- **DB connection held during ffmpeg** — `caption_burner.py` and `reframer.py` were holding the write lock while ffmpeg ran (10-30s per clip). Refactored: DB read → close connection → run ffmpeg → open new connection → write result
- **`db.init_db()` in pipeline** — Removed unnecessary call from `process_video()`. Init only happens once at server startup. Duplicate call competed with worker pool
- **`creator` form field not parsed** — `POST /jobs` used bare `str` annotations for form fields alongside `File(...)`. FastAPI requires `Form(...)` annotation for multipart form fields. Added `Form(...)` to `clips`, `platforms`, `mode`, `creator` in the upload endpoint

### Test result (post-fix)
- 57-second video → 2 clips in ~50 seconds
- Both clips captioned (7155KB vs 5949KB source → real burn confirmed)
- 65 words, 18 groups per clip in DB
- Creator slug correctly propagated to output directory
- `/clips/{full-uuid}/captions` returns words + groups correctly

---

## 2026-09-08 — Documentation system established

- Created `CLAUDE.md` at project root
- Created `docs/` with PROJECT_STATUS, ARCHITECTURE, CHANGELOG, ROADMAP, KNOWN_ISSUES, DECISIONS

---

## 2026-09-02 — Full caption system

### Added
- `engine/captions/` package: `presets.py`, `extractor.py`, `renderer.py`
- Three caption presets: **Impact** (yellow highlight, pop animation), **Aura** (cyan/glow, fade), **Glowing Bold** (orange, scale, 3 words max)
- ASS subtitle format with karaoke word-level events (per-word color + scale override)
- `clips.caption_data` and `clips.caption_settings` columns in DB
- `db.get_clip_captions()` and `db.update_clip_captions()` helpers
- Completely rewrote `engine/renderers/caption_burner.py` to use ASS pipeline
- Four new API endpoints:
  - `GET /captions/presets`
  - `GET /clips/{id}/captions`
  - `PUT /clips/{id}/captions`
  - `POST /clips/{id}/re-render`
- Caption editor in dashboard modal: Style / Words / Position tabs
- Canvas real-time preview overlay (2-pass draw: stroke then fill)
- Word list editor with editable timestamps
- Position controls with safe-zone info
- "Save style" and "Re-render MP4" buttons

### Fixed
- `setPosition(pos, btn)` crash — was reading global `event`, now takes `btn` as parameter passed from `onclick="setPosition('top', this)"`

---

## 2026-09-02 — Local upload fix (video-only files)

### Fixed
- Local upload (PC video) failing completely when file has no audio stream
- Added `_has_audio_stream()` ffprobe check in `engine/transcription.py` before attempting audio extraction
- Added no-audio fallback in `engine/analyzers/candidate_detector.py`: position-based scoring (30–50 pts) when words list is empty
- Fixed local upload title: pipeline now extracts original filename from `{uuid}_{originalname}.mp4` path pattern

---

## 2026-09-02 — Library persistence across restarts

### Fixed
- `/jobs` endpoint returning empty list after server restart (was only reading in-memory `_jobs` dict)
- Now reads from DB with `SELECT j.*, v.creator_slug, v.video_slug, v.source_title ...` JOIN
- Overlays live `_jobs` data (real-time status + result) on top of DB records
- Added `creator: str = ""` parameter to both `POST /jobs` and `POST /jobs/from-url`
- Creator passed through `_run_job()` → `process_video()` → stored in DB

### Fixed
- Dashboard showing duplicate jobs when multiple jobs contributed to same video group
- JS now tracks `jobIds` Set per video group, renders one "DOWNLOAD ALL" button per contributing job

---

## (earlier) — Initial build

- FastAPI + SQLite + uvicorn stack
- 12-step pipeline: INGEST → QA/GATE
- WorkerPool with 2 daemon threads
- yt-dlp for URL ingestion
- faster-whisper + openai-whisper fallback transcription
- FAIL CLOSED QA gate
- Dashboard SPA: Library tab, clip modal, video playback
- Publishers (TikTok, Instagram, YouTube) — stubs, inactive
- Analytics collector — stub, inactive
- ContentAutopsy learning — stub, inactive
