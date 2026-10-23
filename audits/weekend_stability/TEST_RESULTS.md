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

## Regression Tests (2026-10-23)

| Area | Status | Notes |
|------|--------|-------|
| Server health | PASS | ok |
| Worker threads alive | PASS | 2/2 |
| Disk space | PASS | 248.9 GB free |
| DB integrity | PASS | no orphans, no zombies |

---
<!-- Tests will be updated as the supervisor runs tasks -->
