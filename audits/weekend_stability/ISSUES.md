# Known Issues

## Open Issues

### ISS-001: GTA4 job status inconsistency
- **Job**: 36499131-b5c0-4574-a994-43737a9c0f8f
- **Status**: COMPLETED but with error "Server restarted — job was interrupted"
- **Impact**: Cosmetic — 15 clips exist and pass QA
- **Fix**: Would require updating historical job record (blocked by constraint)
- **Workaround**: Job is functional, just shows misleading error field

### ISS-002: 8 clips with PENDING/PENDING QA
- **Query**: SELECT id, output_path FROM clips WHERE technical_qa='PENDING'
- **Likely cause**: Old clips rendered before QA gate was implemented
- **Impact**: Low — these are old clips, not in active review flow
- **Fix needed**: Run retrospective QA check on these clips

### ISS-003: generate-top/generate-series had sqlite3.Row.get() bug
- **Status**: FIXED (2026-10-23)
- **Impact**: Both endpoints returned 500 for any job
- **Fix**: Added video = dict(video) before .get() calls

### ISS-004: 8 PENDING QA clips from 2026-09-17 with no output files
- **Query**: SELECT id FROM clips WHERE technical_qa='PENDING'
- **Cause**: Pre-QA clips rendered before automatic QA gate was implemented; output files were later deleted
- **Impact**: Low — these clips won't appear as PASS in library, won't block any flow
- **Fix needed**: Update technical_qa/visual_qa to 'FAIL' — blocked by "No modificar: Clips originales" constraint
- **Status**: OPEN (awaiting user authorization to update clip records)

### ISS-005: generate-top/generate-series ignored crop_config
- **Status**: FIXED (2026-10-23)
- **Impact**: Jobs with GAMING_STACKED_FIT manual crop would get center-cropped clips when re-rendered
- **Fix**: Both endpoints now read crop_config and pass to renderer
- **Affected jobs**: 8 jobs with GAMING_STACKED_FIT crop_configs

---
## Closed Issues

- crop_converter formula wrong (FIXED 2026-10-23)
- render-concat hardcoded x_offset=0 (FIXED 2026-10-23)
- _MIN_FACE_AREA_FRAC too large for gaming corner webcam (FIXED 2026-10-23)
- SSE banner showed job ID instead of title for completed jobs (FIXED 2026-10-23)
- Duplicate check blocked reprocessing deleted videos (FIXED 2026-10-23)
