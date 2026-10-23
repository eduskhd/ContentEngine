# Performance — Concat vs FFmpeg

**Status:** PENDING — Concat not yet installed

---

## Methodology

Each clip rendered 3 times; median taken. Same source video, same time range, same target resolution.

Hardware: Windows 11, [CPU/GPU to be filled in]

---

## Baseline (FFmpeg)

From existing pipeline benchmarks (see `audits/library_media_architecture/`):
- Average render time: TBD from pipeline_timings table
- Hardware encoder: detected via `hw_accel.detect_encoder()`

---

## Expected Concat overhead

- MCP process startup: ~2–5s (one-time per render)
- Project creation: ~0.1s
- Media import: ~0.5s
- Per-operation MCP roundtrip: ~50ms
- Export time: comparable to FFmpeg at same CRF (both use FFmpeg internally)

Total overhead estimate: +5–8s per clip (process startup + MCP operations)

---

## Results (to fill after Phase 6)

| Metric | FFmpeg | Concat | Delta |
|--------|--------|--------|-------|
| Avg render time (30s clip) | — | — | — |
| Avg render time (60s clip) | — | — | — |
| Process startup overhead | N/A | — | — |
| Export CRF=18 file size | — | — | — |
| GPU utilization | — | — | — |
| Peak RAM | — | — | — |
