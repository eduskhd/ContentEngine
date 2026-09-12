# clipping-engine

**Type:** Project skill  
**Scope:** Deep audit and improvement of the ContentEngine clipping pipeline  
**When to use:** When clip quality degrades, after ingesting new video types, or when planning a pipeline upgrade

---

## Purpose

Perform a structured quality audit and targeted improvement of the clipping pipeline.  
Follows: AUDIT → DIAGNOSE → IMPLEMENT → VERIFY.

---

## Trigger

```
/clipping-engine
```

---

## Pipeline Architecture (V2 — as of 2026-09-12)

```
VIDEO → INGEST → PROXY(360p 2fps) → TRANSCRIPTION → CANDIDATE DETECTION
     → VISUAL+AUDIO(parallel) → PLATFORM FIT → VIRALITY SCORING
     → SKILLS → RENDER(1-pass: trim+crop+caption) → QA/GATE → CLIPS READY
```

Key files:
- `engine/pipeline.py` — 12-step orchestrator
- `engine/transcription.py` — faster-whisper singleton, word_timestamps=True, vad_filter
- `engine/analyzers/candidate_detector.py` — dual-pass: sentence-peak + sliding-window
- `engine/analyzers/semantic_analyzer.py` — heuristic scoring, 8 emotion types, hook phrases
- `engine/analyzers/virality_scorer.py` — 9-component ensemble + optional LLM (claude-haiku)
- `engine/analyzers/visual_analyzer.py` — motion + face + brightness via proxy video
- `engine/analyzers/audio_analyzer.py` — RMS energy + dynamic range via librosa
- `engine/renderers/render_clip.py` — 1-pass FFmpeg render, hardware encoding, parallel
- `engine/captions/extractor.py` — word extraction, confidence filtering, timestamp normalization
- `engine/captions/renderer.py` — ASS subtitle builder (karaoke-style per-word highlight)
- `engine/config.py` — all thresholds and model settings

---

## V2 Changes (2026-09-12)

| Area | Change | Impact |
|------|--------|--------|
| Transcription | `whisper_model = "small"` (was "base") | Better word timestamps |
| Transcription | `vad_filter=True` added to faster-whisper call | Fewer silence hallucinations |
| Hook detection | `first_words = w_in[:15]` (was `[:10]`) | Catches slower-paced openers |
| Candidates | Intro/outro skip zones (first/last 3%) | No title cards or CTAs as candidates |
| Candidates | Min composite score threshold (15.0) | Drops weak candidates before DB persist |
| Virality | Position bonus bug fixed: uses `video_duration` not `end_s` | Accurate position weighting |
| Captions | `caption_min_word_confidence=0.30` filter in extractor | No garbled words in captions |
| Auto QA | `_check_technical_qa()` in render_clip | Actual PASS/FAIL instead of always PENDING |
| Sliding window | Smart-cut window unified to `CONFIG.smart_cut_window` (was hardcoded 8.0) | Consistent boundaries |

---

## 10 Audit Areas

### 1. Transcription Quality
- Model: `CONFIG.whisper_model` (currently "small")
- VAD filter: enabled
- Word probability: check `probability` distribution in a fresh job
- Cache: `videos.words_json` — verify reuse works across jobs on same file

**Red flags:** words with `probability < 0.3`, repeated phrases (hallucination), missing words at sentence boundaries.

### 2. Candidate Quality
- Dual-pass detection: sentence-peak + sliding-window
- Intro/outro zones: `CONFIG.intro_skip_ratio` and `outro_skip_ratio`
- Min composite: `CONFIG.min_candidate_composite`
- Diversity: max 2 candidates per `content_type`
- IoU deduplication threshold: `CONFIG.deduplicate_iou_threshold`

**Red flags:** all candidates from same type (all "hook"), candidates overlapping > 70%, candidates from first/last 5% of video.

### 3. Smart Cutting
- `find_smart_start` / `find_smart_end` in `semantic_analyzer.py`
- Window: `CONFIG.smart_cut_window` (12s) — used consistently in both passes
- Checks: pause ≥ 0.5s, sentence boundaries, hook phrases

**Red flags:** clips starting mid-sentence, clips cutting a word in half at end.

### 4. Scoring Accuracy
- Composite formula in `_composite()`: semantic(0.25) + hook(0.25) + emotion(0.15) + standalone(0.10) + shareability(0.10) + retention(0.15)
- Virality formula: 9 components (or 10 with LLM)
- Position bonus: linear decay over full video duration

**Red flags:** all clips score 40-60 (no discrimination), position bonus wrong for long videos, hook score always 0.

### 5. Series Detection
- Groups by `MAX_NARRATIVE_GAP = 120s` gap
- Requires `MIN_SERIES_DURATION = 60s` arc
- Parts: `MIN_PART_S=18s`, `MAX_PART_S=45s`, up to 4 parts
- Gated by `CONFIG.generate_series`

**Red flags:** series of 1 part (shouldn't exist), series covering 90%+ of the video.

### 6. Caption Quality
- `caption_min_word_confidence = 0.30` in extractor
- Group size: `max_words=4` default
- ASS color format: `&HAABBGGRR` (inverted alpha, BGR byte order)
- Animation: pop/scale/bounce/fade
- Timing: per-word highlight via karaoke events

**Red flags:** garbled words visible, captions off-screen, misaligned timing.

### 7. Reframe
- Center crop only (`_compute_crop_filter`)
- No face-tracking reframe (not implemented — known limitation)
- For 16:9 source: crops sides. For portrait source: crops top/bottom.

**Red flags:** action happening at edge of frame (check visually).

### 8. Auto QA
- `_check_technical_qa` in `render_clip.py`
- Checks: file size > 0, video stream present, duration within ±40%, fps ≥ 10
- Warnings: duration deviation 15-40% (non-fatal)
- `visual_qa` still PENDING (not implemented)

**Red flags:** clips with `technical_qa=FAIL` not being rejected by prepublish gate (should be automatic per FAIL CLOSED rule).

### 9. Speed
- Transcription: ~300-450s cold (base/small), instant warm (cache)
- Render: parallel via `ThreadPoolExecutor(max_workers=max_par)`
- Hardware encoding: QSV → NVENC → libx264 veryfast
- Proxy analysis: 360p 2fps, opened once for all candidates

**Red flags:** warm job (cached transcript) taking > 60s, render taking > 30s per clip on hardware encoder.

### 10. Cost
- LLM: batches 8 candidates per claude-haiku call
- LLM: skips if `ANTHROPIC_API_KEY` not set
- LLM: caches results in `candidates.score_breakdown["llm_analysis"]` — no re-call on retry
- Whisper: "small" model, CPU+int8 — no API cost

**Red flags:** repeated LLM calls for same candidates on retry, LLM enabled without API key (check logs for warnings).

---

## How to Run an Audit

### Step 1 — Read current state
```
Read engine/config.py
Read engine/pipeline.py (timing section)
Query: SELECT count(*), avg(virality_score), min(virality_score) FROM candidates WHERE job_id=?
Query: SELECT technical_qa, count(*) FROM clips GROUP BY technical_qa
```

### Step 2 — Check a recent job
```
GET /jobs/{id}/timing   → per-stage wall-clock
GET /jobs/{id}          → candidates, clips, scores
```

### Step 3 — Sample output
- Open a clip in the dashboard
- Check caption alignment (are words in sync?)
- Check crop (is the speaker centered?)
- Check virality reasons (do they match what you see?)

### Step 4 — Tune if needed
Only change thresholds in `engine/config.py`. Do not change scoring weights without benchmarking before/after.

---

## Output Format

```
## clipping-engine Audit — [date]

### Pipeline Version
V2 (2026-09-12)

### Findings by Area
| Area | Status | Issue | Recommendation |
|------|--------|-------|----------------|
| Transcription | ✅ | — | — |
| Candidates | ⚠️ | All hook type | Lower IoU threshold to 0.4 |
...

### Config Delta (if changes recommended)
| Setting | Current | Recommended | Reason |
|---------|---------|-------------|--------|

### Verdict
PIPELINE HEALTHY / NEEDS TUNING / NEEDS FIX
```

---

## Notes

- Do NOT change scoring weights without a before/after benchmark on at least 3 different videos.
- Do NOT touch `engine/captions/renderer.py` ASS color encoding — the `&HAABBGGRR` format is correct.
- Do NOT disable the QA FAIL CLOSED gate — `technical_qa=FAIL` clips must be rejected.
- The re-render endpoint (`POST /clips/{id}/re-render`) uses `burn_captions_ass()` not `render_clips_onepass()` — they use different encoders (libx264 vs HW). This is intentional.
