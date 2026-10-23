# Known Limitations — Concat Integration

**Last updated:** 2026-10-23

---

## Blockers (must resolve before any production use)

| ID | Limitation | Impact | Resolution path |
|----|-----------|--------|-----------------|
| KL-001 | Unsigned binary — Smart App Control may block on Windows 11 | Cannot run concat.exe | Check SAC state; if "On", compile from Rust source or disable SAC |
| KL-002 | `captions_add` parameters undocumented | Word-level karaoke captions unknown | Experiment in Phase 6; use title_add fallback |

---

## Design constraints (known, accepted)

| ID | Limitation | Impact | Workaround |
|----|-----------|--------|-----------|
| KL-003 | Crop API uses fractional edges, not pixels | x_offset → offsetX conversion needs calibration | crop_converter.py formula; calibrate in Phase 6 |
| KL-004 | `concat.lock` — one headless process per project dir | Cannot share project dirs between parallel renders | Each clip gets its own project directory (already implemented) |
| KL-005 | GPU blur/glow export stalls (unconfirmed v0.2.8) | Export may timeout | export_timeout_s=600; cancel on timeout; don't use blur effects initially |
| KL-006 | Simultaneous GUI + MCP not supported | Developer cannot preview project while adapter runs | Use separate projects for automation vs manual editing |
| KL-007 | No Direct3D 11 on some systems (#480) | GPU rendering crash | Falls back to software rendering if GPU unavailable |

---

## Feature gaps vs FFmpeg pipeline

| Feature | FFmpeg | Concat | Status |
|---------|--------|--------|--------|
| ASS karaoke captions (word-level highlight) | ✅ | ❓ (`captions_add` undocumented) | TBD Phase 6 |
| One-pass trim+crop+caption | ✅ | Separate operations (trim, frame, caption) | More steps, same result |
| Hardware encoding (NVENC/QSV) | ✅ | ✅ DirectML (Windows v0.2.6+) | Verify in Phase 6 |
| Portrait 9:16 output | ✅ | ✅ (confirmed 1080×1920) | OK |
| Per-frame crop keyframes | ✅ (via keypoints) | ✅ (`keyframe_set`) | OK |
| Batch rendering | ✅ (ThreadPoolExecutor) | ⚠️ One process per project | Use per-worker instances |
| ASS subtitle format | ✅ | ❌ (own caption system) | Pass pre-captioned video OR use title_add |

---

## Not planned for initial integration

- Transitions between clips (not needed — single-clip renders)
- Audio effects (only basic audio passthrough needed)
- Color grading / LUTs (not in current pipeline)
- Templates (future consideration)
- Speed changes beyond 1x (not in current pipeline)
