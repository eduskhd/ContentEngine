# Concat Integration — Final Report

**Status:** PHASES 1–4 COMPLETE (code) · Phases 5–10 pending Concat installation  
**Date:** 2026-10-23

---

## What is done

### Phase 1 — Verified ✅
- Concat v0.2.8 researched: Rust, MCP stdio JSON-RPC, headless confirmed
- 1080×1920 export confirmed
- All MCP tools catalogued with verified parameters
- AGPL-3.0 license reviewed: no risk for private internal use
- Critical blocker identified: Smart App Control (SAC) may block unsigned binary
- Captions gap identified: `captions_add` undocumented

### Phase 2 — Implemented ✅ (untested — pending installation)
- `integrations/concat/` — isolated adapter package
- `MCPClient` — stdio JSON-RPC subprocess wrapper (Windows + POSIX)
- `ConcatAdapter` — full render workflow (create/import/trim/frame/caption/export)
- `crop_converter.py` — x_offset → Concat offsetX fraction formula
- Feature flag: `concat_enabled = False` in `engine/config.py`
- All failures isolated via `ConcatNotAvailable`, `ConcatTimeout`, `ConcatMCPError`
- FFmpeg pipeline **unchanged**

### Phase 3 — Applied ✅
- Alembic migration `ef29ee6b5fa6`: `clips.render_engine` column
  - 729 existing clips → `'ffmpeg'`
  - 8 phantom clips → `'LEGACY_UNKNOWN'`
- Alembic migration `856de02e25ba`: `clip_variants` table (17 columns, 2 indexes)
- DB helpers: `create_clip_variant`, `get_clip_variants`, `update_clip_variant`

### Phase 4 — Implemented ✅
- New Job form: engine radio buttons (FFmpeg default / Concat experimental)
- Concat status badge: "checking..." → "(disabled)" / "(v0.2.8) experimental"
- `render_engine` passed in `/jobs/from-url` payload
- Guard: `concat` silently falls back to `ffmpeg` if `concat_enabled=False`
- `render_engine` stored in `jobs.metadata` for non-ffmpeg jobs
- API endpoint: `GET /engines/concat/status`
- API endpoint: `GET /clips/{clip_id}/variants`

---

## What remains blocked on Concat installation

| Phase | Description | Blocker |
|-------|-------------|---------|
| Phase 5 | Library version indicators + compare actions | Needs real variants to display |
| Phase 6 | 12-clip experiment | Needs Concat working |
| Phase 7 | EditPlan common structure | Design ready; implementation after Phase 6 validates API |
| Phase 8 | Comparator view | Needs real variant data |
| Phase 9 | Publishing protection audit | Can review code now (publishing unchanged) |
| Phase 10 | Full E2E tests | Needs Concat installed and SAC verified |
| Phase 11 | Drive sync + final report | After all phases complete |

---

## NEXT STEP — Install Concat

```powershell
# Step 1: Check Smart App Control state
Get-MpComputerStatus | Select-Object SmartAppControlState
# If "On" → SAC will block the unsigned binary → stop here, discuss options
# If "Evaluation" or "Off" → proceed

# Step 2: Download and install v0.2.8
# From: https://github.com/jub0t/Concat/releases/tag/v0.2.8
# File: concat-0.2.8-windows-x86_64-setup.exe
# Install to default path: %LOCALAPPDATA%\Programs\Concat\

# Step 3: Verify
concat.exe --version

# Step 4: Enable in config
# engine/config.py: concat_enabled = True

# Step 5: Run smoke test
python -c "from integrations.concat import concat_available; print(concat_available())"
```

---

## Criteria for integration readiness (Phase 10 checklist)

1. FFmpeg jobs: no regression ✅ (pipeline unchanged)
2. Concat selectable in New Job ✅
3. Independent variants generated (pending)
4. Engine registered per variant (pending)
5. Library shows engine origin (pending — Phase 5)
6. FFmpeg vs Concat comparison (pending — Phase 8)
7. No existing clip overwritten ✅ (by design)
8. Publishing intact ✅ (publications unchanged)
9. Real export tests pass (pending — Phase 10)
10. Concat failures don't affect normal jobs ✅ (all exceptions isolated)
