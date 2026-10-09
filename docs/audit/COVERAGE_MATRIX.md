# ContentEngine Functional Coverage Matrix
_Audit date: 2026-10-09_

## API Endpoints

| Method | Path | Category | Tested | Result | Notes |
|--------|------|----------|--------|--------|-------|
| GET | /health | Core | ✅ | PASS | db/ffmpeg/workers all ok |
| GET | /workers/stats | Core | ✅ | PASS | 2/2 alive |
| GET | /admin/status | Core | ✅ | PASS | Returns queue, errors, storage |
| GET | /admin/orphans | Core | ✅ | PASS | Detects missing files |
| GET | /performance/summary | Core | ✅ | PASS | Stage times present |
| GET | /dashboard | UI | ✅ | PASS | SPA loads, all tabs render |
| POST | /jobs | Pipeline | ⬜ | SKIP | Requires URL + ffmpeg run |
| POST | /jobs/from-url | Pipeline | ⬜ | SKIP | Requires valid URL |
| GET | /jobs | Pipeline | ✅ | PASS | Returns job list |
| GET | /jobs/url-info | Pipeline | ⬜ | SKIP | Requires URL |
| GET | /jobs/url-check | Pipeline | ⬜ | SKIP | Requires URL |
| GET | /jobs/{id} | Pipeline | ✅ | PASS | Returns job details |
| GET | /jobs/{id}/events | Pipeline | ⬜ | SKIP | SSE stream |
| GET | /jobs/{id}/analysis | Pipeline | ✅ | PASS | Returns candidate analysis |
| GET | /jobs/{id}/timing | Pipeline | ✅ | PASS | Per-stage timings |
| GET | /jobs/{id}/series | Pipeline | ✅ | PASS | Returns detected series |
| POST | /jobs/{id}/generate-top | Pipeline | ✅ | **FIXED** | Was missing QA call — fixed |
| POST | /jobs/{id}/generate-series/{sid} | Pipeline | ✅ | **FIXED** | Was missing QA call — fixed |
| POST | /jobs/{id}/retry | Pipeline | ⬜ | SKIP | Requires failed job |
| POST | /jobs/{id}/missed-moments | Pipeline | ⬜ | SKIP | Requires running job |
| GET | /jobs/{id}/missed-moments | Pipeline | ⬜ | SKIP | |
| GET | /clips | Clips | ✅ | PASS | Returns paginated clips |
| GET | /clips/{id} | Clips | ✅ | PASS | Returns clip detail |
| GET | /clips/{id}/download | Clips | ✅ | PASS | File served |
| GET | /clips/{id}/preview | Clips | ✅ | PASS | Video preview |
| GET | /clips/{id}/thumbnail | Clips | ✅ | PASS | Thumbnail served |
| GET | /clips/{id}/captions | Clips | ✅ | PASS | Returns ASS caption data |
| PUT | /clips/{id}/captions | Clips | ⬜ | SKIP | Requires manual test |
| POST | /clips/{id}/re-render | Clips | ✅ | PASS | Caption re-burn works |
| POST | /clips/{id}/retranscribe | Clips | ⬜ | SKIP | Requires audio |
| POST | /clips/{id}/smart-reframe | Reframe | ✅ | **FIXED** | Face filter bug fixed |
| GET | /clips/{id}/smart-reframe | Reframe | ✅ | PASS | Polls status |
| GET | /clips/{id}/smart-reframe/{vid}/video | Reframe | ✅ | PASS | Serves variant |
| POST | /clips/{id}/smart-reframe/{vid}/accept | Reframe | ✅ | **FIXED** | Persists framing_plan |
| DELETE | /clips/{id} | Clips | ✅ | PASS | Deletes clip + files |
| POST | /clips/bulk-delete | Clips | ⬜ | SKIP | |
| GET | /clips/{id}/publications | Clips | ✅ | PASS | |
| POST | /clips/{id}/prepare | Clips | ⬜ | SKIP | Publishing only |
| POST | /clips/{id}/generate-metadata | Clips | ⬜ | SKIP | |
| POST | /clips/{id}/evaluate | Clips | ⬜ | SKIP | |
| GET | /clips/{id}/evaluation | Clips | ⬜ | SKIP | |
| GET | /evaluations | Clips | ⬜ | SKIP | |
| GET | /evaluations/export | Clips | ⬜ | SKIP | |
| GET | /review/pending | Review | ✅ | ⚠️ | Badge capped at 200 (query limit) |
| POST | /review/{id}/approve | Review | ✅ | PASS | Sets decision=PUBLISH |
| POST | /review/{id}/reject | Review | ✅ | PASS | Sets decision=REJECT |
| POST | /clips/{id}/return-to-review | Review | ⬜ | SKIP | |
| GET | /captions/presets | Captions | ✅ | PASS | Returns preset list |
| GET | /jobs/{id}/download-all | Export | ⬜ | SKIP | |
| GET | /videos | Videos | ✅ | PASS | Returns video list |
| PATCH | /videos/{id}/creator | Videos | ⬜ | SKIP | |
| POST | /videos/bulk-assign | Videos | ⬜ | SKIP | |
| DELETE | /videos/{id} | Videos | ✅ | PASS | |
| POST | /videos/bulk-delete-impact | Videos | ⬜ | SKIP | |
| POST | /videos/bulk-delete | Videos | ⬜ | SKIP | |
| GET | /videos/{id}/thumbnail | Videos | ✅ | PASS | |
| GET | /videos/{id}/package | Packages | ✅ | PASS | |
| POST | /videos/{id}/package/ensure-publications | Packages | ✅ | PASS | Idempotent, used in backfill |
| POST | /videos/{id}/package/publish | Packages | ⬜ | SKIP | Publishing inactive |
| GET | /videos/{id}/package/batches | Packages | ⬜ | SKIP | |
| POST | /videos/backfill-packages | Packages | ⬜ | SKIP | |
| POST | /videos/{id}/verify-rights | Videos | ⬜ | SKIP | Always sets rights_verified=1 |
| GET | /creators | Creators | ✅ | PASS | 15 creators returned |
| POST | /creators | Creators | ✅ | PASS | |
| GET | /creators/{id} | Creators | ✅ | PASS | |
| PUT | /creators/{id} | Creators | ⬜ | SKIP | |
| DELETE | /creators/{id} | Creators | ✅ | PASS | |
| GET | /creators/{id}/impact | Creators | ⬜ | SKIP | |
| GET | /creators/{id}/packages | Creators | ✅ | PASS | |
| GET | /packages | Packages | ✅ | PASS | |
| GET | /packages/{id} | Packages | ✅ | PASS | |
| PUT | /packages/{id} | Packages | ⬜ | SKIP | |
| DELETE | /packages/{id} | Packages | ⬜ | SKIP | |
| POST | /packages/{id}/items | Packages | ⬜ | SKIP | |
| DELETE | /packages/{id}/items | Packages | ⬜ | SKIP | |
| POST | /packages | Packages | ⬜ | SKIP | |
| GET | /publications | Publishing | ✅ | PASS | |
| POST | /publications | Publishing | ⬜ | SKIP | |
| GET | /publications/{id} | Publishing | ✅ | PASS | |
| PUT | /publications/{id} | Publishing | ⬜ | SKIP | |
| DELETE | /publications/{id} | Publishing | ⬜ | SKIP | |
| POST | /publications/{id}/mark-ready | Publishing | ⬜ | SKIP | |
| POST | /publications/{id}/mark-published | Publishing | ⬜ | SKIP | |
| POST | /publications/{id}/metrics | Publishing | ⬜ | SKIP | |
| POST | /publications/{id}/cancel | Publishing | ⬜ | SKIP | |
| POST | /publications/bulk-create | Publishing | ✅ | PASS | Used in backfill |
| POST | /publications/bulk-action | Publishing | ⬜ | SKIP | |
| POST | /publications/remediate-metadata | Publishing | ⬜ | SKIP | |
| GET | /publications/download-zip | Publishing | ⬜ | SKIP | |
| GET | /publications/stats | Publishing | ✅ | PASS | |
| GET | /collections | Library | ⬜ | SKIP | |
| POST | /collections | Library | ⬜ | SKIP | |
| GET | /collections/{id} | Library | ⬜ | SKIP | |
| PUT | /collections/{id} | Library | ⬜ | SKIP | |
| DELETE | /collections/{id} | Library | ⬜ | SKIP | |
| GET | /collections/{id}/videos | Library | ⬜ | SKIP | |
| POST | /collections/{id}/items | Library | ⬜ | SKIP | |
| DELETE | /collections/{id}/items | Library | ⬜ | SKIP | |
| GET | /upload-batches | Batches | ⬜ | SKIP | |
| POST | /upload-batches | Batches | ⬜ | SKIP | |
| GET | /upload-batches/{id} | Batches | ⬜ | SKIP | |
| POST | /upload-batches/{id}/pause | Batches | ⬜ | SKIP | |
| POST | /upload-batches/{id}/resume | Batches | ⬜ | SKIP | |
| POST | /upload-batches/{id}/retry-errors | Batches | ⬜ | SKIP | |
| GET | /storage/summary | Storage | ✅ | ⚠️ | 1 missing video file detected |
| POST | /storage/scan | Storage | ⬜ | SKIP | |
| GET | /yt/queue-status | YouTube | ⬜ | SKIP | Inactive |
| POST | /yt/retry-pending | YouTube | ⬜ | SKIP | Inactive |
| GET | /youtube/status | YouTube | ⬜ | SKIP | Inactive |
| POST | /publications/{id}/youtube-upload | YouTube | ⬜ | SKIP | Inactive |
| GET | /yt-uploads/{id} | YouTube | ⬜ | SKIP | Inactive |
| POST | /yt-uploads/{id}/cancel | YouTube | ⬜ | SKIP | Inactive |
| GET | /publications/{id}/yt-upload | YouTube | ⬜ | SKIP | Inactive |
| POST | /yt-upload-sessions/{id}/update-privacy | YouTube | ⬜ | SKIP | Inactive |
| GET | /analytics/summary | Analytics | ⬜ | SKIP | Stub, inactive |
| POST | /analytics/collect | Analytics | ⬜ | SKIP | Stub, inactive |
| POST | /learning/autopsy | Learning | ⬜ | SKIP | Stub, inactive |
| GET | /learning/weight-suggestions | Learning | ⬜ | SKIP | Stub, inactive |
| GET | /oauth/{platform}/start | OAuth | ⬜ | SKIP | Never used |
| GET | /oauth/{platform}/callback | OAuth | ⬜ | SKIP | Never used |

## Dashboard UI Surfaces

| Surface | Tested | Result | Notes |
|---------|--------|--------|-------|
| Overview tab — KPI cards | ✅ | PASS | 494 clips, 22 approved, 472 pending |
| Overview — Recent Clips table | ✅ | PASS | Scores, decisions visible |
| Overview — Export Evals buttons | ⬜ | SKIP | |
| Library — Packages view (default) | ✅ | PASS | Shows package cards |
| Library — Creator sidebar | ✅ | PASS | 15 creators, Todos filter works |
| Library — All Videos filter | ✅ | PASS | Shows all 35 videos |
| Library — All Creators filter | ✅ | PASS | |
| Library — Clips tab | ⬜ | SKIP | |
| Library — Search | ⬜ | SKIP | |
| Library — Bulk select | ⬜ | SKIP | |
| Clip modal — Play, Download | ✅ | PASS | |
| Clip modal — Reframe tab | ✅ | **FIXED** | Accepted state badge works |
| Clip modal — Captions editor | ⬜ | SKIP | |
| Review tab — Pending list | ✅ | ⚠️ | Badge shows 200 (capped at query limit) |
| Review tab — Approve/Reject | ✅ | PASS | Works |
| Review tab — Filter dropdown | ✅ | PASS | Pending/Approved/Rejected |
| Review tab — Select mode | ⬜ | SKIP | |
| Jobs tab | ✅ | PASS | Shows 37 jobs |
| New Job — URL/Upload tabs | ✅ | PASS | Both tabs visible |
| New Job — Creator autocomplete | ✅ | PASS | Visible |
| New Job — Advanced Options | ⬜ | SKIP | |
| New Job — Duplicate detection | ⬜ | SKIP | |
| Analysis tab | ⬜ | SKIP | nav-sec, rarely used |
| Publishing tab | ⬜ | SKIP | inactive |
| Stats tab | ⬜ | SKIP | |

## DB Table Integrity

| Table | Row Count | Issues |
|-------|-----------|--------|
| videos | 35 | 1 missing file (benign) |
| jobs | 37 (33 COMPLETED, 4 FAILED) | None |
| candidates | 1258 | series_part=4 concentration (design flaw) |
| clips | 494 | 0 missing files; all QA'd |
| publications | 544 | 35 orphan refs to deleted clips (33 archived, 2 failed — benign) |
| prepublish_decisions | — | FK-safe |
| clip_packages | 100 | All intact |
| clip_package_items | 485 | All intact |
| creators | 15 | None |
| reframe_variants | — | None |

## QA Gate

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| technical_qa=PASS | 484/494 | 484 | PASS |
| technical_qa=WARN | 10 (fps_ok) | 10 | PASS (WARN = not FAIL, not rejected) |
| visual_qa=PASS | 494 | 494 | PASS (after backfill) |
| visual_qa=PENDING | 0 | 0 | PASS (after backfill) |
| prepublish_decision=PENDING | 0 | 0 | PASS (after backfill) |
