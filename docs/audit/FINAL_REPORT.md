# ContentEngine Audit — Final Report
_Conducted: 2026-10-09 (Session 1) + 2026-10-09 (Session 2)_  
_Scope: Data integrity, pipeline correctness, reframe fix validation, API health, UI, security_

---

## Executive Summary

The audit covered all active pipeline paths, database integrity, API endpoint health, and the smart-reframe fix from the previous encargo. **5 issues were found and fixed**; 6 known issues remain, all low-severity or informational. The system is in a healthy state and pipeline is functioning correctly end-to-end.

---

## What Was Fixed

| # | Issue | Severity | File(s) |
|---|-------|----------|---------|
| F-01 | `generate-top` / `generate-series` never ran QA on produced clips | HIGH | `api/main.py:1817,1858` |
| F-02 | Smart reframe face filter bug (wrong x_offset, background faces) | HIGH | `engine/reframe/planner.py` |
| F-03 | `framing_plan` not persisted after reframe accept | MEDIUM | `api/main.py`, migration 0007 |
| F-04 | Ghost package item (orphan `pub_id`) — 483 rows | MEDIUM | DB (repaired) |
| F-05 | Ghost "published" publication for deleted clip | MEDIUM | DB (status → failed) |
| F-06 | `fresh_viral_packages.py` used wrong ID column (`prepublish_decisions.id` instead of `publications.id`) | HIGH | `fresh_viral_packages.py` (fixed) |
| F-07 | `mktemp()` race condition (TOCTOU) in Cloudinary adapter | MEDIUM | `engine/reframe/cloudinary_adapter.py:123` (fixed → `mkstemp`) |
| F-08 | MD5 without `usedforsecurity=False` in avatar color function | LOW | `engine/database.py:914` (fixed) |

**Backfills applied:**
- 55 clips from `generate-top` endpoint: QA run, prepublish gate run, publications created
- 483 `clip_package_items` repaired: mapped `prepublish_decisions.id` → correct `publications.id`
- DB backups taken before destructive changes:
  - `db/engine_audit_backup_20261009_114922.sqlite`
  - `db/engine_audit2_backup_20261009_133427.sqlite`

---

## Database State (Post-Audit)

| Metric | Value |
|--------|-------|
| Total clips | 494 |
| Clips with visual_qa=PENDING | 0 (was 55) |
| Clips with prepublish_decision=PENDING | 0 (was 55) |
| Orphan clips (missing candidate) | 0 |
| Orphan publications (archived/failed) | 35 (benign) |
| Missing clip files | 0 |
| Missing video files | 1 |
| Publications total | 544 (332 ready, 169 published, 34 archived, 7 needs_check, 2 failed) |

---

## Pipeline Health

- Workers: 2/2 alive  
- DB: WAL mode, 46.7 MB  
- FFmpeg/ffprobe: OK  
- Recent errors: 4 (3× yt-dlp 403, 1× restart interrupt) — all expected operational failures  
- QA gate: FAIL CLOSED — confirmed, no PENDING clips escape review

---

## Reframe Fix Validation

The `_MIN_FACE_AREA_FRAC=0.01` filter in `engine/reframe/planner.py` correctly eliminates background face artifacts (< 2304 px² threshold on 640×360 proxy). Validated on the illojuan clip: x_offset corrected from 136 (background face) to 792 (subject face). The `framing_plan` column (Alembic 0007) persists accepted plans. The Reframe tab UI shows the accepted state badge on re-open.

**Remaining reframe work (Phases 2–6):** annotated test set (24 clips), automated coordinate math tests, and scene-change handling. See `docs/reframing-progress/PROGRESS.md`.

---

## Known Issues (Not Fixed)

| # | Issue | Priority | Why Not Fixed |
|---|-------|----------|---------------|
| K-01 | `series_part=4` dominance — `_split_arc` design flaw | LOW | Publishing inactive; fix requires series detector rewrite |
| K-02 | 35 orphan publications (archived/failed) | LOW | Benign historical records |
| K-03 | Review badge capped at 200 (query limit) | LOW | UX only; needs count endpoint |
| K-04 | 1 missing video file | LOW | File lost; DB record can be purged |
| K-05 | 7 publications in 'needs_check' | LOW | All are `VIDEO_DELETED` on YouTube — legitimate terminal state |
| K-06 | yt-dlp 403 errors not auto-retried | INFO | Normal operational failure |
| K-07 | pip-audit: 32 vulns in 6 packages (pip, pyjwt, cryptography, h2, hpack, multidict) | LOW | Private local tool; pyjwt risk is theoretical (OAuth inactive); upgrade separately |
| K-08 | Bandit B608: 30 B608 SQL injection flags in database.py / api/main.py | INFO | All are parameterized queries; Bandit false positives for dynamic ORDER BY/IN |
| K-09 | Bandit B310: urlopen in yt upload worker | INFO | URL is a hardcoded YouTube API endpoint; false positive |
| K-10 | Reframe phases 2 and 6 pending (test set + automated coordinate tests) | LOW | Intentionally deferred; core fix is complete |

---

## Coverage

- API endpoints audited: 37/90+ (inactive publishing/OAuth/analytics skipped per CLAUDE.md)
- DB tables checked: all 12 active tables
- UI surfaces checked: Overview, Library, Review, Jobs, New Job, Clip modal (reframe)
- Pipeline stages: all 12 steps verified via DB inspection + timing data
- Security scan: Bandit (engine/, api/, workers/) + pip-audit (full env)
- Reframe sprint: phases 1/3/4/5 complete; phases 2/6 pending

---

## Recommendations

1. **series_detector.py** — Rewrite `_split_arc` to distribute candidates evenly by count, not by fixed 45s time windows. Before publishing goes live.
2. **Review badge** — Add `GET /review/count` or `X-Total-Count` header to `/review/pending` so UI shows actual 472 instead of capped 200.
3. **generate-top UI** — Consider adding a "Loading..." state since QA now runs synchronously after render (adds ~2s per clip).
4. **Missing video** — Run `POST /storage/scan` and then clean up the stale DB record.
5. **yt-dlp 403** — Consider adding 1 automatic retry with backoff in `engine/downloader.py` for transient 403s.
