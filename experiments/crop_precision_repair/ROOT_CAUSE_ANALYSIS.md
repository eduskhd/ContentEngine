# Root Cause Analysis — Crop Precision Repair
**Date:** 2026-10-20  
**Status:** RC1 confirmed + fixed. RC2 documented.

---

## Coordinate pipeline traced

```
New Job (canvas)
  → normalized [0-1] coords (canvas px / canvas.width|height)
  → POST /crop-configs { gameplay_rect, facecam_rect, src_width, src_height }
  → crop_configs table: gameplay_x/y/w/h, facecam_x/y/w/h (floats 0-1), src_width, src_height
  → render_one_clip():
      cw = crop_config["src_width"] or src_w   ← BUG RC1
      ch = crop_config["src_height"] or src_h  ← BUG RC1
      main_region = [norm_x * cw, norm_y * ch, norm_w * cw, norm_h * ch]
  → _compute_stacked_fit_filter(main_region, src_w, src_h)
      gx, gy, gw, gh = int(v) for v in main_region  ← wrong pixel values
      FFmpeg: crop={gw}:{gh}:{gx}:{gy},...
```

---

## RC1 — Resolution mismatch (CRITICAL, FIXED)

### Where it lives
`engine/renderers/render_clip.py` lines 143–144

### Cause
The frame preview endpoint (`/jobs/url-frame`, `/jobs/prepare-preview`) uses yt-dlp format  
`"bestvideo[height<=720]/bestvideo/best"` which selects a **720p stream** (typically 1280×720).

The extracted JPEG frame is 1280×720.  
The canvas normalizes coords relative to this JPEG: `norm_x = px_x / canvas.width` where `canvas.width = wrap.clientWidth` (sized to match the JPEG display dimensions).

These normalized coords are stored in `crop_configs` along with `src_width=1280, src_height=720`.

The actual download (`engine/downloader.py` line 174) uses format  
`"bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best"` → downloads **1080p** (1920×1080).

`ffprobe` on the downloaded file returns `width=1920, height=1080`.  
Pipeline sets `src_w=1920, src_h=1080`.

But the renderer reads:
```python
cw = crop_config.get("src_width") or src_w   # → 1280 (WRONG for 1080p video)
ch = crop_config.get("src_height") or src_h  # → 720  (WRONG)
```

Result: FFmpeg receives pixel coordinates computed for 1280×720 but applied to a 1920×1080 frame.

### Example
User selects gameplay at norm_x=0.10, norm_y=0.0, norm_w=0.80, norm_h=1.0

| | cw/ch used | FFmpeg crop |
|---|---|---|
| **Buggy** | 1280×720 | crop=1024:720:128:0 on 1920×1080 frame |
| **Correct** | 1920×1080 | crop=1536:1080:192:0 on 1920×1080 frame |

The buggy crop extracts the wrong region — shifted left and too narrow.

### Fix
```python
# Before (render_clip.py line 143):
cw = crop_config.get("src_width") or src_w
ch = crop_config.get("src_height") or src_h

# After:
cw = src_w   # always use actual video dimensions
ch = src_h   # normalized coords are resolution-independent
```

Normalized coords (0-1) encode a **proportional region**. They are resolution-independent for same-AR videos. Multiplying by the actual video dimensions always gives the correct pixel location.

---

## RC2 — Preview/render parity (MEDIUM, RESOLVED by RC1 fix)

### Cause
Preview runs FFmpeg on the **720p stream URL**; render runs on the **1080p downloaded file**.

Before RC1 fix: both used 1280×720 pixel coords → preview "correct" on 720p stream, render "wrong" on 1080p file.

After RC1 fix: preview uses 1280px-wide coords on 720p stream; render uses 1920px-wide coords on 1080p file. Both reference the same proportional region. For same-AR content (both 16:9), the visual result is identical.

### Remaining gap
If a video has non-standard SAR (non-square pixels), the JPEG frame dimensions (display) may differ from ffprobe coded dimensions. FFmpeg's `crop` filter operates in coded pixel space.

**Mitigation:** For gaming/YouTube content, SAR is always 1:1. Not an active issue in practice.

---

## RC3 — canvas.width without DPR (LOW)

### Cause
`canvas.width = wrap.clientWidth` uses CSS pixels. On HiDPI displays (devicePixelRatio=2), the canvas bitmap is half the physical resolution, but coordinate math is unaffected since normalization uses the same canvas.width. Visual rendering is blurry but coordinates are correct.

**No fix needed for crop accuracy.** Only affects visual quality of the selector.

---

## RC4 — validation_status gate (MEDIUM)

### Cause
Renderer only applies manual crop if:
```python
crop_config.get("validation_status") in ("validated", "confirmed_no_preview")
```

If user skips preview and confirms directly, `validation_status` may remain `"pending"` → renderer silently falls back to auto framing plan.

**Fix needed:** Add `"pending"` to the accepted statuses when crop_mode is `"manual"` and both rects are present, OR ensure the confirm path always writes `"confirmed_no_preview"`.

---

## Other checks (no issues found)

| Check | Result |
|---|---|
| CSS letterboxing in canvas | No — image fills wrap width, canvas matches |
| devicePixelRatio scaling | No — CSS px / CSS px = 1.0, no DPR issue in coords |
| Coord format [x,y,w,h] | Consistent through all layers |
| facecam_rect y/h swap bug | No — all 4 values passed correctly |
| Crop duplicated in filter | No — only one crop per region in filter |
| Re-render using stale plan | Possible — stored framing_plan on candidate may be outdated |

---

## Files audited

| File | Relevance |
|---|---|
| `dashboard/index.html` | Canvas drawing, normalization, coord sending |
| `api/main.py:4690` | save_crop_config, preview-file, preview-url endpoints |
| `engine/database.py:2495` | create_crop_config storage |
| `engine/renderers/render_clip.py:137` | Denormalization + filter building |
| `engine/ingest.py:54` | ffprobe — coded dimensions |
| `engine/downloader.py:174` | Download format (1080p) |
| `api/main.py:365` | Frame preview format (720p) |
