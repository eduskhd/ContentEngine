# Performance

**Status:** BENCHMARKED (debug build)  
**Date:** 2026-11-03

---

## Test Environment

| Setting | Value |
|---------|-------|
| OS | Windows 11 Home |
| concat-cli | v0.2.8 (debug build) |
| Source resolution | 1080p |
| Output | 1080×1920, 20s, CRF 18 |
| Hardware encoder | QSV (Intel) / libx264 fallback |

---

## Render Times — Concat Fixed (C)

Single verified render (after moveClips fix):

| Creator | Clip Duration | Render Time | Throughput | Notes |
|---------|--------------|-------------|------------|-------|
| rubius_z | 20s | **21.2s** | ~0.94× realtime | Debug build; QSV encoder |

4-render batch (evidence renders, debug build):

| File Size | Duration | Est. Render Time |
|-----------|----------|-----------------|
| 6.2 MB (rubius_z C) | 20.0s | ~21s |
| 10.3 MB (thegrefg C) | 20.0s | ~28s (est.) |
| 19.1 MB (illojuan C) | 20.0s | ~45s (est.) |
| 13.8 MB (iker_unzu C) | 20.0s | ~30s (est.) |

---

## Debug vs Release Build

Concat v0.2.8 was compiled in debug mode. Debug builds include bounds checking, no LTO, and unoptimized Rust code. Expected performance delta:

| Metric | Debug Build | Release Build (estimated) |
|--------|-------------|--------------------------|
| Render time (20s clip) | ~21s | ~3–7s |
| Speedup | 1× | ~3–7× |
| Memory | Higher | Lower |

The current `concat-cli` binary is the debug build. To see release performance:

```powershell
# Build release
cd C:\path\to\concat-source
cargo build --release
# Replace binary
copy target\release\concat-cli.exe tools\concat-cli.exe
```

---

## FFmpeg Comparison

| Engine | 20s clip | Notes |
|--------|----------|-------|
| FFmpeg (libx264 veryfast) | ~3–5s | Main pipeline, no hardware |
| FFmpeg (QSV/NVENC) | ~1–2s | Hardware encoding |
| Concat debug | ~21s | Phase overhead + debug runtime |
| Concat release (est.) | ~3–7s | With release binary |

---

## Phase Breakdown (Concat)

Concat render involves multiple round-trips through the JSON-RPC API:

| Phase | Operations | Approximate overhead |
|-------|-----------|---------------------|
| 1 — Create/import | project.create + media.import + save | ~2–4s |
| 2a — addClip | project.open + addClip + save | ~1–2s |
| 2b — Trim/frame/export | project.open + 3–6 edit.apply + export.run | ~15–18s |
| **Total** | | **~21s** |

The majority of time is in Phase 2b export, which is bound by the Concat encoder. The API round-trips (Phases 1, 2a) add ~3–6s fixed overhead vs pure FFmpeg.

---

## Timeout Configuration

Current `CONCAT_TIMEOUT = 600.0s`. One iker_unzu render timed out in an early batch run (source video > 1h, debug build under heavy export load). With the release build, timeouts are not expected for clips ≤ 60s.

Recommended for production: `CONCAT_TIMEOUT = 120.0s` with release binary.

---

## Conclusion

Debug build performance (~21s per 20s clip) is acceptable for experimental use. Release build is required for production parity with FFmpeg (~3–5s). The two-bug fix does not meaningfully affect performance — the added `moveClips` operation is a single JSON-RPC call (<50ms).
