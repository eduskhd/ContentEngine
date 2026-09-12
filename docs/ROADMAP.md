# Roadmap

Items are ordered by value, not by size. Nothing here is committed — reprioritize freely.

```
1. Quality & Stability          ✅ done
2. Publishing Center            ✅ done (2026-09-10)
   2.5 Production Readiness     ✅ done (2026-09-10)
3. Social API Integrations      ← NEXT
   - YouTube Shorts
   - Instagram Reels
   - TikTok
4. Real Performance Metrics
5. Creator Analytics
6. Creator Fit + Platform Fit + Retention Prediction
7. Content Strategy AI
8. Commercial Scaling / External Users
```

## CURRENT — Production Readiness Gate (done 2026-09-10)
Phase 2.5 complete. Critical bugs fixed, security hardened, observability added.
See `docs/PRODUCTION_READINESS.md` for full assessment.

## NEXT — YouTube Shorts API Integration
Connect `POST /publications/{id}/publish` to YouTube Data API v3 for Shorts upload.
Requires: OAuth setup, refresh token management, upload endpoint, status polling.
Provider pattern: `publishers/youtube.py` already exists as stub.

## THEN — Instagram Reels API Integration
Connect Instagram Graph API for Reels upload.
Requires: Facebook Developer App, OAuth, video upload endpoint.

## THEN — TikTok Content Posting API
Connect TikTok Content Posting API v2.
Requires: TikTok developer account, OAuth v2, video upload.

## THEN — Scheduling / Automatic Publishing
Add scheduled jobs: `scheduled_at` field in publications already present.
Worker pool extension: PublicationWorker polls `publications WHERE status='scheduled' AND scheduled_at<=now()`.

## THEN — Metrics Collection
After clips are published, collect views/likes/comments via platform APIs.
`publication_metrics` table is ready. Analytics tab can show predicted vs actual.

## THEN — Predicted vs Actual Performance
Connect `publication_metrics` data to `candidates.virality_score` predictions.
`learning/autopsy.py` stub exists. Enable recalibration loop.

---

## Tier 1 — Core pipeline improvements

These directly improve the quality of the clips you get.

### Smarter candidate scoring
- Hook detection based on sentence structure ("did you know", "here's the thing", questions)
- Emotional arc scoring — look for tension + resolution within a candidate window
- Speaker count awareness — prioritize single-speaker segments

### Caption quality
- Auto-detect and correct proper nouns from whisper output
- Support multi-speaker caption coloring (different highlight colors per speaker)
- Font selection: support custom .ttf fonts instead of only system fonts
- Caption vertical position auto-avoid: detect faces in top third and push captions down

### Reframe quality
- Face-tracking crop (currently center-crop only for most cases)
- Action-region detection for videos without faces

---

## Tier 2 — Usability

### Dashboard
- Search / filter library by creator, status, date
- Bulk select + bulk download
- Progress bar per step (TRANSCRIBING → DETECTING → GENERATING, etc.) using SSE stream
- Clip duration badge on thumbnail
- Caption preview: show word count, estimated reading speed, warn if too fast

### Job submission
- Drag-and-drop upload zone
- Batch URL submission (paste multiple URLs)
- Per-job preset selection at submission time

---

## Tier 3 — Infrastructure

### Worker pool
- Configurable worker count (currently hardcoded to 2)
- Job cancellation: `DELETE /jobs/{id}` that stops in-flight work
- Priority queue: bump jobs manually via API

### Config
- Runtime config edit via API (no server restart needed for thresholds)
- Per-creator scoring profiles

---

## Out of scope (do not implement)

- Social publishing (TikTok/Instagram/YouTube API) — not needed for private use
- Analytics collection — not needed without publishing
- Multi-user auth / accounts
- Cloud storage (S3, GCS) — everything is local by design
