# production-readiness

**Type:** Project skill  
**Scope:** Full production readiness assessment for ContentEngine  
**When to use:** Before milestone releases, before exposing to new users, after architectural changes

---

## Purpose

Converts the Phase 2.5 readiness framework into a repeatable, structured audit. Reviews every system dimension and emits a clear readiness verdict. Never declares PRODUCTION READY without live evidence.

---

## Trigger

```
/production-readiness
```

---

## Readiness Tiers

| Verdict | Meaning |
|---------|---------|
| **NOT READY** | Critical blockers present. Do not proceed. |
| **INTERNAL ALPHA READY** | Stable for single-operator internal use. Not safe for external users. |
| **LIMITED BETA READY** | Safe for trusted external users with known limitations documented. Auth required. |
| **PRODUCTION READY** | Hardened, multi-user, observable, tested under load. |

---

## Audit Checklist

### 1 — Job System

- [ ] Jobs persist across server restarts (check `jobs` table status after restart)
- [ ] Zombie job cleanup runs at startup (`WorkerPool._cleanup_zombie_jobs`)
- [ ] In-flight jobs marked FAILED after restart (not stuck in INGESTING/RENDERING)
- [ ] `_jobs` dict rebuilt from DB on `GET /jobs` (not only from memory)
- [ ] Job status transitions are complete: QUEUED → INGESTING → TRANSCRIBING → ANALYZING → RENDERING → QA → COMPLETED / FAILED
- [ ] No duplicate `job_id` generation (same UUID in `_jobs` dict and `jobs` table)

### 2 — Queue & Workers

- [ ] `job_queue` table records survive restart (WAL mode confirmed)
- [ ] Max attempts = 3 enforced
- [ ] Running → queued reset on startup for stuck entries
- [ ] Worker count configurable at startup (`python server.py N`)
- [ ] Two simultaneous jobs stable (2 workers default)
- [ ] Third job queues correctly (no crash, no deadlock)
- [ ] Worker thread health: daemon threads don't block shutdown

### 3 — Retries & Idempotency

- [ ] `POST /jobs/{id}/retry` only allowed when status = FAILED
- [ ] Retry does not create duplicate `jobs` rows (INSERT OR IGNORE / skip if exists)
- [ ] Transcript cache survives retry (words_json reused, transcription skipped)
- [ ] Proxy cache survives retry (proxy_path reused)
- [ ] Simultaneous retry requests don't create duplicate entries (race condition check)

### 4 — Crash Recovery

- [ ] Server kill mid-pipeline → job marked FAILED on next startup
- [ ] Retry of crashed job → pipeline runs from start, caches hit
- [ ] Partial render (some clips succeed, some fail) → successful clips saved, job continues to QA
- [ ] `GET /admin/orphans` detects clips with missing files

### 5 — Storage Lifecycle

- [ ] Temp ZIP files deleted after download (BackgroundTasks cleanup)
- [ ] `output/audio/` WAV files: documented as cache (safe to delete)
- [ ] `output/proxies/` proxy files: documented as cache (safe to delete)
- [ ] Master video / source never auto-deleted
- [ ] Clips deleted only via explicit DELETE endpoint
- [ ] No unbounded file accumulation in `%TEMP%` or working directory
- [ ] `output/` directory structure confirmed: uploads/, downloads/, audio/, proxies/, thumbnails/, {creator}/{video}/

### 6 — Database

- [ ] WAL mode confirmed (`PRAGMA journal_mode`)
- [ ] Foreign keys enforced (`PRAGMA foreign_keys=ON`)
- [ ] `busy_timeout=30000` prevents lock errors
- [ ] 14 indexes on high-frequency query columns present
- [ ] All schema migration via `_add_column_if_missing` (non-destructive)
- [ ] `pipeline_timings` table present
- [ ] No unbounded growth in any table (pagination present for jobs, clips, videos)

### 7 — Performance

- [ ] Cold run baseline measured (transcription dominates — document expected range)
- [ ] Warm run baseline measured (transcript cache — document expected range)
- [ ] Time to first clip recorded
- [ ] `GET /jobs/{id}/timing` returns per-stage breakdown
- [ ] `GET /performance/summary` returns aggregated metrics
- [ ] Hardware encoder detection working (QSV/NVENC/CPU confirmed)
- [ ] Transcription device setting documented (cpu vs cuda)

### 8 — Observability

- [ ] `GET /health` returns server status
- [ ] `GET /workers/stats` returns worker pool state
- [ ] `GET /admin/orphans` detects storage inconsistencies
- [ ] `GET /performance/summary` returns pipeline benchmarks
- [ ] Server logs (`server.log`, `server_err.log`) present and rotating
- [ ] No sensitive data in logs (no API keys, no auth tokens, no PII)

### 9 — Security (condensed — full audit via `/video-security`)

- [ ] SSRF protection active in `engine/downloader.py`
- [ ] File upload path traversal protection in `api/main.py`
- [ ] Upload size limit (10 GB) enforced
- [ ] FFmpeg commands use list form (no `shell=True`)
- [ ] No hardcoded secrets in code
- [ ] CORS policy documented and appropriate for deployment context

### 10 — E2E Repeatability

- [ ] URL submission → pipeline → clips → download: end-to-end confirmed
- [ ] File upload → pipeline → clips → download: end-to-end confirmed
- [ ] Restart → job persistence → manual retry → completion: confirmed
- [ ] Caption edit → re-render → new file: confirmed
- [ ] Creator assignment → collection management: confirmed

### 11 — Known Limitations (must be documented before each tier)

For **LIMITED BETA READY**, these must be resolved or explicitly accepted:
- [ ] Authentication added (API key, session, or OAuth)
- [ ] `workspace_id` or `user_id` isolation added to data model
- [ ] Authorization checks on all resource endpoints
- [ ] Rate limiting per user

For **PRODUCTION READY**, additionally:
- [ ] Load testing completed (concurrent users, concurrent jobs)
- [ ] Automated test suite covering critical paths
- [ ] Formal error classification (retryable vs non-retryable)
- [ ] Monitoring/alerting configured
- [ ] Backup strategy for `db/engine.sqlite`
- [ ] Storage scaling strategy documented

---

## Scoring

Count passing items in each section. A section FAILS if any item is:
- Unchecked AND marked as required for the target tier
- An active regression from a previously verified state

### Tier Gate Rules

**INTERNAL ALPHA READY** (current baseline):
- Sections 1–5 must pass fully
- Section 6 must pass
- Section 9: SSRF, upload, FFmpeg checks must pass
- Section 10: URL and file upload flows confirmed

**LIMITED BETA READY**:
- All above, plus Section 11 limited-beta items resolved
- Section 8 (observability) must pass

**PRODUCTION READY**:
- All above, plus Section 11 production items resolved
- Load testing evidence required

---

## Output Format

```
## production-readiness Assessment — [date]

### Sections
| Section | Items | Pass | Fail | Skip |
|---------|-------|------|------|------|
| 1 Job System | N | n | n | n |
...

### Blockers
(list any FAIL items with severity)

### Accepted Limitations
(list items skipped with documented reason)

### Verdict
**[NOT READY / INTERNAL ALPHA READY / LIMITED BETA READY / PRODUCTION READY]**

Reasoning: ...

### Next Steps for Tier Upgrade
1. ...
```

---

## Notes

- Read `docs/PRODUCTION_READINESS.md` as baseline — it documents Phase 2.5 verified state.
- When reassessing, compare against that baseline: look for regressions, not just new findings.
- Never declare PRODUCTION READY based on code review alone — require live E2E evidence.
- Update `docs/PRODUCTION_READINESS.md` after each formal assessment.
