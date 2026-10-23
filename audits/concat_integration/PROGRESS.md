# Concat Integration — Progress

**Started:** 2026-10-23
**Status:** PHASE 1 IN PROGRESS

---

## Phase Checklist

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Verify Concat — repo, API, Windows compat, license, limitations | ✅ DONE |
| Phase 2 | Isolated adapter `integrations/concat/` + feature flag | ✅ DONE (untested — pending install) |
| Phase 3 | Clip variants model + Alembic migrations | ✅ DONE |
| Phase 4 | Engine selector in New Job UI | ✅ DONE |
| Phase 5 | Library: version indicators + compare actions | ⏳ PENDING (needs real variants) |
| Phase 6 | Experiment on 12 representative clips | ⏳ BLOCKED — Concat not installed |
| Phase 7 | Common EditPlan structure + translator | ⏳ PENDING (design ready) |
| Phase 8 | Comparator view | ⏳ PENDING (needs real variant data) |
| Phase 9 | Publishing protection audit | ⏳ PENDING |
| Phase 10 | Required tests | ⏳ BLOCKED — Concat not installed |
| Phase 11 | Reports + Drive sync | 🔄 IN PROGRESS |

---

## Key constraints

- FFmpeg remains default engine — NEVER replaced
- Concat behind `concat_enabled = false` feature flag
- No modification of existing clips, jobs, packages, publications
- Concat failures must not block the main render queue
- No forced install into Content Engine's Python env
- No mass data operations without prior authorization
- AGPL-3.0 implications must be reviewed before production use
- Only implement verified API operations — no invented commands

---

## Phase 1 findings

*Pending — investigation in progress*
