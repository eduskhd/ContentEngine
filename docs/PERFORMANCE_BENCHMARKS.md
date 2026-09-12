# Performance Benchmarks

Last updated: 2026-09-10  
Environment: Windows 11, Intel Core i5/i7 with QSV (Intel Quick Sync Video), 16GB RAM

---

## Benchmark: 2-minute 1080p video (3 clips)

| Run type | Transcription | Proxy | Visual+Audio | Render (3 clips) | Total |
|----------|--------------|-------|-------------|-----------------|-------|
| Cold (no cache) | ~300s | ~3–5s | ~5–8s | ~21s | ~360s |
| Warm (transcript cached) | 0s | 0s | ~5s | ~21s | ~28s |

**Note:** Cold run time is dominated entirely by CPU-based transcription.

---

## Stage breakdown (cold run, 2-min 1080p)

| Stage | Time | Notes |
|-------|------|-------|
| Ingest | 1–2s | ffprobe only |
| Proxy generation | 3–5s | 360p 2fps, ultrafast preset, cached after |
| Transcription | 100–400s | faster-whisper base, CPU. Scales with video length |
| Candidate detection | 1–3s | Semantic scoring, N candidates |
| Visual + Audio (parallel) | 5–8s | OpenCV on proxy; RMS on WAV |
| Platform fit | <1s | Heuristic scoring |
| Virality scoring | <1s | Ensemble formula |
| Series detection | <1s | Clustering algorithm |
| Skills | <1s | Hook analyzer, virality predictor |
| Render (3 clips, QSV parallel) | 15–25s | 1080×1920, ASS captions burned in |
| QA + Gate | 1–2s | ffprobe per clip |
| **Total (cold)** | **~330–450s** | |
| **Total (warm)** | **~28s** | |

---

## Transcription scaling (CPU, faster-whisper base)

Transcription is approximately 1–3× real-time on CPU, depending on speech density.

| Video duration | Estimated transcription time |
|---------------|------------------------------|
| 2 min | 1–5 min |
| 10 min | 5–20 min |
| 30 min | 15–60 min |
| 1 hour | 30–120 min |
| 2 hours | 60–240 min |

**Time to first clip (cold):** Approximately equal to transcription time + 30s.  
**Time to first clip (warm, transcript cached):** ~28s for 2-min video; scales with render time.

---

## Render performance (QSV hardware encoding)

| Clips | Resolution | Render time |
|-------|-----------|-------------|
| 1 clip (30s) | 1080×1920 | ~7s |
| 3 clips (parallel) | 1080×1920 | ~21s |
| 5 clips (parallel, max 3 at once) | 1080×1920 | ~35s |

Without QSV (CPU libx264 veryfast):
- 1 clip (30s): ~25–40s
- 3 clips (2 parallel): ~55–80s

**Hardware encoding speedup: 3–5× compared to CPU libx264.**

---

## Optimization impact (Phase 2.5, 2026-09-10)

| Optimization | Before | After | Improvement |
|-------------|--------|-------|-------------|
| One-pass render (trim+crop+caption) | ~65–150s (3 clips) | ~21s | 3–7× |
| QSV hardware encoding | CPU: ~65–90s | QSV: ~21s | 3–4× |
| Proxy for visual analysis | ~15–30s | ~5–8s | 3–4× |
| Transcript cache (warm run) | ~300s | 0s | ∞ |
| Whisper model singleton | +5s reload per job | 0s | eliminates reload |
| Parallel visual+audio analysis | ~20s sequential | ~8s parallel | ~2× |

---

## Memory usage (estimated)

| Component | RAM |
|-----------|-----|
| Server base | ~150MB |
| faster-whisper base model | ~200MB |
| Per active FFmpeg render | ~200–500MB |
| OpenCV per frame | ~50–100MB |
| Per worker thread | ~20MB |
| **Total at rest (2 workers)** | **~400MB** |
| **Total during peak (2 jobs, 6 FFmpeg renders)** | **~2–4GB** |

---

## Concurrent job capacity

| Workers | Active Pipelines | Render Threads | Peak RAM |
|---------|-----------------|----------------|----------|
| 2 (default) | 2 | 6 (3 per QSV job) | ~2–4GB |
| 4 | 4 | 12 | ~4–8GB |

**Recommendation:** 2 workers on machines with 8GB RAM; 4 workers on 16GB+.

Transcription serializes because the Whisper singleton is shared — 2 simultaneous transcription jobs will take 2× as long. Rendering parallelizes fully.

---

## Bottleneck ranking

### 1. Transcription (CPU, single-threaded)
- Dominant cost for cold runs
- Fix: GPU transcription (`device="cuda"`) = 10–20× faster
- Fix: Upgrade to whisper `large-v3` on GPU for better accuracy

### 2. Whisper model singleton (serializes transcription across jobs)
- Second job waits for first transcription to finish
- Fix: Separate transcription subprocess or queue

### 3. Single-machine Python process
- Memory leak or crash affects all jobs
- Fix (scale): Separate worker processes, Docker isolation

---

## Cost estimation

### Self-hosted (current setup)
- All processing is local: **$0 per video hour** (marginal compute cost)
- Storage: ~200–500 MB per processed video hour (source + clips + audio + proxy)
  - At $0.02/GB/month ≈ $0.01/video hour/month

### Cloud deployment (estimated, future)

| Component | Cost | Per 1h video |
|-----------|------|--------------|
| Transcription (OpenAI Whisper API) | $0.006/min | $0.36 |
| Cloud VM compute (e4s v5, 4 vCPU) | $0.15/hr active | $0.05–0.15 |
| Storage (S3, first 50GB free) | $0.023/GB/month | $0.01 |
| Egress (clip downloads) | $0.09/GB | ~$0.01–0.05 per clip |
| **Estimated total per video hour** | | **~$0.40–0.60** |
| **Estimated cost per generated clip** | | **~$0.08–0.15** |

Note: Transcription via OpenAI API is the dominant cloud cost. Local Whisper eliminates it entirely.

---

## Load test summary

Not formally load-tested. Capacity estimates from architecture review:

| Concurrent jobs | Expected behavior |
|----------------|------------------|
| 1 | Fully stable |
| 2 | Stable (both workers active) |
| 3–5 | Stable — jobs queue, process in order |
| 6–10 | Queue grows; transcription serializes; renders remain parallel |
| 10+ | Queue latency increases; no degradation of running jobs |

**Recommendation:** Start with 2 workers. Monitor `/admin/status` for queue depth. Add workers if queue depth consistently exceeds 5.
