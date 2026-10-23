# Next Action

## Current priority: crop_audit_fix

Run the clipping-engine skill audit, then verify crop_converter formula and test a Concat render.

### Specific steps
1. Query recent clips for framing_plan x_offset values
2. Run crop_converter center test (x_offset=656 should give offsetX≈0.0)
3. POST /clips/{clip_id}/render-concat on a recent clip with a framing_plan
4. Verify output with ffprobe (dimensions, audio, size)
5. Fix any issues found

### Why this first
Concat render crop was broken in 3 different ways before the last session. Need to confirm all 3 fixes are working correctly with a real test before moving on.

### If blocked
If the Concat binary fails, skip to concat_render_verify task.
If crop_converter is correct and Concat renders correctly, mark crop_audit_fix as done and start gaming_compositor_fix.
