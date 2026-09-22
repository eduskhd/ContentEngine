# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Currently a single operator (the builder). Building toward content agencies and prolific creators who process more than 10 hours of video per month and feel the pain of per-minute credit models, cloud latency, and privacy exposure. The future paying user is a small team (2–5 people) or a solo professional who manages multiple creator accounts or clients.

Primary jobs the operator does when opening the tool:

1. **Submit a new video and get clips fast** — paste URL or upload file, configure clips/platform/creator, submit, then return when the pipeline has finished. Speed from submission to downloadable clip is the performance bar.
2. **Manage a library of creators and their content** — find a creator, see their video history, locate specific clips, assign and organize content across sources, and track what has been reviewed or published.

Review (approve / reject / reset) is a secondary but essential step between pipeline output and distribution; it is not the entry point but must be frictionless.

## Product Purpose

ContentEngine is a local-first AI clipping engine. It ingests any long-form video (URL or file), runs a 12-step pipeline fully on-device, and produces captioned 9:16 short-form clips ready for social distribution — without sending data to any cloud, without per-minute credits, and without an internet connection after the initial download.

Success for the operator means: submit a video, come back to a set of ranked clips with karaoke captions, approve the best ones, and have them ready to distribute — all in under 10 minutes for a cached source.

## Positioning

The only AI clipping tool that processes without limits, without cloud, and without privacy compromise. Competitors (OpusClip, Klap, Riverside) are architecturally cloud-first; their local-processing claims are thin wrappers. ContentEngine's privacy and unlimited-processing guarantees are not features that can be added to a SaaS — they are the architecture.

Differentiating mechanism: one-pass FFmpeg render (trim + crop + ASS caption burn in a single call), dual-pass candidate detection with IoU deduplication, faster-whisper with path-based transcript cache, and hardware encoder auto-detection (QSV → NVENC → libx264). Cold run ~360s; hot (cached) run ~28s.

## Operating Context

- Runs on a single Windows machine (localhost:8000), accessed via browser
- Operator submits jobs, the pipeline runs in background worker threads (2 workers)
- Review happens asynchronously: the operator returns to the Review tab to approve or reject candidates
- Clips are downloaded directly or prepared for publishing via the Publishing tab
- Content spans multiple creators and source platforms (YouTube primarily, also local files)
- No scheduling, no cloud storage — everything lives on local disk and SQLite

## Capabilities and Constraints

**Working today:**
- 12-step pipeline: INGEST → PROXY(360p/2fps) → TRANSCRIPTION → CANDIDATE DETECTION → VISUAL + AUDIO ANALYSIS (parallel) → PLATFORM FIT → VIRALITY SCORING → SKILLS → RENDER → QA/GATE → CLIPS READY
- Faster-whisper transcription with path-based cache (0s on repeated runs)
- Dual-pass candidate detection (sentence-peak + sliding-window, IoU 0.5 dedup)
- One-pass FFmpeg: trim + crop/scale + ASS karaoke captions in a single call
- Hardware encoding: auto-detect QSV → NVENC → libx264 veryfast
- ASS word-level karaoke captions with in-dashboard caption editor (3 presets)
- Creator library with filtering, bulk actions, and collection support
- Review queue with approve/reject/reset workflow
- Publishing Center (manual prep; social API stubs exist but are inactive)
- SQLite WAL mode with zombie-job recovery and ghost-data protection

**Not yet active:**
- Face-tracking reframe (center-crop only today)
- Social publishing APIs (YouTube/TikTok/Instagram stubs present, OAuth not configured)
- Multi-user / workspace isolation
- Scheduling / auto-publish

**Terminology used in the product:**
- *Job* — one processing run of a source video
- *Candidate* — a detected clip segment (start/end times, scores) before rendering
- *Clip* — the rendered output file with captions
- *Creator* — an attributed source account or channel
- *Preset* — a named caption style configuration

**Undecided:**
- Final product name (ContentEngine is a placeholder)
- Monetization model (license, SaaS, or open-core)
- Target platform for first commercial release (Windows installer, Docker, or VPS)

## Brand Commitments

No binding brand commitments at this time. "ContentEngine" is the placeholder name used in code, docs, and the dashboard. No logo, color, or typographic system has been formalized.

## Evidence on Hand

- Fully working pipeline with benchmarks: ~360s cold run, ~28s hot run, ~21s re-render only
- Competitive analysis against OpusClip, Klap, Vizard, Munch, Descript, Riverside, VEED, CapCut (docs/strategy/PRODUCT_STRATEGY_2026-09-14.md)
- Real processed videos: MrBeast, Rick Astley, NBA content, Spanish-language business content
- Processing cost: ~$0.001–0.005/min vs. $0.097/min for OpusClip Pro

## Product Principles

1. **Local-first is the product.** Data never leaves the machine. This is not a privacy feature — it is the architecture. Every decision that would require a cloud round-trip is wrong by default.
2. **The pipeline is the product; the UI serves the pipeline.** The operator is in flow. Friction in submission, review, or export wastes their time in a way that a slow render does not.
3. **Human review is the quality gate.** The pipeline produces ranked candidates; the operator decides what ships. Do not automate approval or silently discard output.
4. **Build for the operator who scales.** The single user today is the template for the agency workflow tomorrow. Decisions about library organization, creator management, and bulk actions should hold at 10× the current volume.
5. **Clarity over cleverness.** This is a professional tool, not a demo. Labels name the action and its effect. No decorative language, no UI theater.
