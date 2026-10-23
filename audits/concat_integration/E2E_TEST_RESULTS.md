# E2E Test Results — Phase 10

**Status:** PENDING — Concat not yet installed

---

## Prerequisites

- [ ] Smart App Control state verified (`Off` or `Evaluation`)
- [ ] `concat-0.2.8-windows-x86_64-setup.exe` installed
- [ ] `concat.exe --mcp headless` launches without SAC block
- [ ] `concat_enabled = True` set in config

---

## Test checklist (Phase 10)

| # | Test | Expected | Result | Notes |
|---|------|----------|--------|-------|
| T01 | FFmpeg jobs run without regression | COMPLETED with clips | ⏳ pending | |
| T02 | `concat_available()` returns False when disabled | False | ✅ verified | `concat_enabled=False` |
| T03 | `concat_available()` returns False when exe missing | False | ✅ verified | exe not installed |
| T04 | `/engines/concat/status` returns disabled status | 200 + enabled=False | ✅ verified | |
| T05 | Concat MCP process starts | Subprocess launched | ⏳ pending install |
| T06 | `project_create` succeeds | Project dir created | ⏳ pending |
| T07 | `media_import` with real video | `createdId` returned | ⏳ pending |
| T08 | `export_start` + `export_status` → MP4 produced | MP4 exists, >0 bytes | ⏳ pending |
| T09 | Export at 1080×1920 | Correct resolution verified | ⏳ pending |
| T10 | Audio synchronized | A/V sync < 100ms | ⏳ pending |
| T11 | `captions_add` / `title_add` fallback | Captions visible in output | ⏳ pending |
| T12 | Project re-openable after render | `project_open` succeeds | ⏳ pending |
| T13 | Metadata stored in `clip_variants` | Row created, verified | ⏳ pending |
| T14 | `create_clip_variant()` persists to SQLite | Row survives server restart | ⏳ pending |
| T15 | Concat timeout → ConcatTimeout raised, job not failed | Warning logged, no queue failure | ⏳ pending |
| T16 | Export failure → ConcatExportFailed, parent clip intact | No clip modification | ⏳ pending |
| T17 | FFmpeg jobs during Concat render | Both complete correctly | ⏳ pending |
| T18 | Library shows correct counts (no duplicates) | clip_variants not in clip count | ⏳ pending |
| T19 | Publishing status of existing clips unchanged | All 757 publications intact | ⏳ pending |
| T20 | SAC-blocked exe → ConcatNotAvailable, server continues | Server stays up, jobs work | ⏳ pending |

---

## To run after Concat installation

```python
# integrations/concat/tests/test_smoke.py (to be created)
from integrations.concat import concat_available, get_adapter
from integrations.concat.adapter import ConcatRenderRequest

# T05-T09: basic render smoke test
req = ConcatRenderRequest(
    source_path=r"C:\...\godeik_5kkt9ibnw9q.mp4",
    output_path=r"C:\...\test_concat_output.mp4",
    start_s=202.0, duration_s=10.0, x_offset=1079,
)
adapter = get_adapter()
result = adapter.render(req)
assert result.success
assert result.width == 1080 and result.height == 1920
```
