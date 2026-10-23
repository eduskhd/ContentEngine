# Test Results

## crop_converter Formula Tests (2026-10-23) ✅

| Test | Input x_offset | Expected offsetX | Actual | Result |
|------|---------------|-----------------|--------|--------|
| Center crop (1920x1080) | 656 | ≈ 0.0 | +0.0000 | PASS |
| Far-left crop | 0 | > 0 (shift right) | +1.0798 | PASS |
| Far-right crop | 1312 | < 0 (shift left) | -1.0798 | PASS |
| Left-of-center | 328 | > 0 | +0.5399 | PASS |
| Right-of-center | 984 | < 0 | -0.5399 | PASS |

## Concat Render Tests (2026-10-23) ✅

| Clip | Variant ID | Render Status | Output Size | Dimensions | FPS | Audio |
|------|-----------|--------------|-------------|------------|-----|-------|
| cc388b39 (GTA4) | 3881ef56 | DONE | 5.8 MB | 1080x1920 | 30fps | AAC 48kHz stereo |

## Pipeline Endpoint Tests (2026-10-23) ✅

| Endpoint | Status | Notes |
|----------|--------|-------|
| GET /health | OK | workers 2/2, disk 248.9GB |
| GET /jobs | OK | |
| GET /clips | OK | |
| GET /creators | OK | correct path (not /library/creators) |
| GET /packages | OK | |
| GET /performance/summary | OK | |
| POST /jobs/{id}/generate-top | FIXED + TESTED | sqlite3.Row.get() bug fixed, 15 clips generated for GTA4 |

## Data Integrity (2026-10-23) ✅

| Check | Result | Notes |
|-------|--------|-------|
| Orphaned candidates | 0 | clean |
| Orphaned clips | 0 | clean |
| Orphaned clip_variants | 0 | clean |
| Zombie jobs (>1hr running) | 0 | clean |
| PENDING QA clips | 8 | old pre-QA clips, not blocking |
| Missing output files (200 PASS sampled) | 0 | all files present |

## Gaming Stacked Layout Tests (2026-10-23) ✅

| Check | Result | Notes |
|-------|--------|-------|
| Jobs with crop_config (GAMING_STACKED_FIT) | 8 | All 8 have gameplay_x + facecam_x set |
| Jobs with clips created AFTER crop_config | 4 | Stacked layout applied during pipeline |
| Test frame extraction (job 179734c2) | PASS | Two-panel 1080x1920 confirmed visually |
| FFmpeg filter `_compute_stacked_fit_filter()` | PASS | vstack: gameplay top + facecam bottom |
| Caption position | PASS | In bottom panel safe zone |
| generate-top passes crop_config | FIXED | Was ignored before 2026-10-23 fix |

## Library & Web UI Audit (2026-10-23) ✅

| Endpoint | Status | Notes |
|----------|--------|-------|
| GET /creators | OK | 25 creators |
| GET /creators/{id} | OK | Full creator detail |
| GET /clips?limit=5 | OK | Paginated |
| GET /clips?limit=5&page=2 | OK | Offset pagination works |
| GET /clips/{id} | OK | has render_engine field |
| GET /clips/{id}/variants | OK | count returned correctly |
| GET /packages?limit=5 | OK | 99 packages total |
| GET /packages/{id} | OK | Package detail |
| GET /performance/summary | OK | Benchmarks returned |
| GET /health | OK | 2/2 workers |
| GET /jobs?limit=3 | OK | Job list |

## DB Final State (2026-10-23) ✅

| Metric | Value |
|--------|-------|
| clips PASS | 734 |
| clips FAIL | 0 |
| clips PENDING | 8 (pre-QA, no files) |
| clip_variants DONE | 32 |
| jobs COMPLETED | 74 |
| jobs FAILED | 14 |
| candidates total | 1984 |
| videos total | 76 |
| clip_packages | 99 |
| creators | 25 |

## Regression Tests (2026-10-23)

| Area | Status | Notes |
|------|--------|-------|
| Server health | PASS | ok |
| Worker threads alive | PASS | 2/2 |
| Disk space | PASS | 248.9 GB free |
| DB integrity | PASS | no orphans, no zombies |
| Library API (11 endpoints) | PASS | all 200 OK |
| Gaming layout (visual) | PASS | two-panel frame confirmed |
| Concat render | PASS | 1080x1920 h264 AAC DONE |

---
