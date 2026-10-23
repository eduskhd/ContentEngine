# Render Comparison — FFmpeg vs Concat

**Status:** PENDING — Concat not yet installed  
**Phase 6 target:** 12 clips (4 gaming, 4 reactions, 4 dynamic)

---

## Clips selected for comparison (Phase 6)

Selection pending. Criteria:
- 4 gaming clips with webcam (GAMING_STACKED_FIT layout)
- 4 reaction / conversation clips (person_static framing)
- 4 dynamic clips (high motion, multi-scene)

Sources: from existing 729 FFmpeg clips in DB, with output files on disk.

---

## Comparison template (per clip)

| Attribute | FFmpeg | Concat |
|-----------|--------|--------|
| Output path | | |
| Duration (s) | | |
| Resolution | 1080×1920 | |
| File size (MB) | | |
| Render time (s) | | |
| technical_qa | | |
| Crop accuracy | | |
| Caption quality | | |
| Audio sync | | |
| Subjective quality | | |

---

## Metrics to capture

1. **Crop alignment** — is subject centered correctly? (visual inspection)
2. **Caption quality** — word-level vs block captions, timing accuracy
3. **Audio sync** — no drift over clip duration
4. **File size** — at CRF=18, comparable to FFmpeg libx264 veryfast?
5. **Render time** — Concat process overhead vs FFmpeg single-pass
6. **Visual quality** — GPU compositor vs software encode quality

---

## Contact sheets

Will be generated once Concat renders are available.  
Target: side-by-side frames at 0%, 25%, 50%, 75%, 100% of each clip.
