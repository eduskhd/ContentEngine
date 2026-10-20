# FFmpeg Filtergraph Audit — Gaming Stacked Compositor

**Date:** 2026-10-20  
**Function:** `_compute_stacked_fit_filter()` in `engine/renderers/render_clip.py`

---

## Filtergraph Structure

```
Input: source video (any resolution)
Output: 1080×1920 (9:16)

[0:v]split=2[main][face];
[main]crop=GW:GH:GX:GY,scale=1080:TOP_H:force_original_aspect_ratio=decrease,pad=1080:TOP_H:(ow-iw)/2:(oh-ih)/2:black[v0];
[face]crop=FW:FH:FX:FY,scale=1080:BOT_H:force_original_aspect_ratio=decrease,pad=1080:BOT_H:(ow-iw)/2:(oh-ih)/2:black[v1];
[v0][v1]vstack=inputs=2[out]
```

Where:
- `GX,GY,GW,GH` = gameplay region in source pixels (denormalized from [0-1] using ACTUAL video dims)
- `FX,FY,FW,FH` = facecam region in source pixels
- `TOP_H = int(1920 * split_fraction)` → even number
- `BOT_H = 1920 - TOP_H` → even number
- Total = 1920 (guaranteed, no gap, no overlap)

---

## Panel Heights by Ratio

| Ratio | split_fraction | Gameplay (TOP_H) | Webcam (BOT_H) | Sum  |
|-------|---------------|-----------------|----------------|------|
| 50/50 | 0.50          | 960px           | 960px          | 1920 |
| 60/40 | 0.60          | 1152px          | 768px          | 1920 |
| 65/35 | 0.65 (default)| 1248px          | 672px          | 1920 |
| 70/30 | 0.70          | 1344px          | 576px          | 1920 |

---

## FIT vs FILL Comparison

| Mode | Scale | Second step | Edge behavior |
|------|-------|-------------|---------------|
| FILL (old v11/v12) | `force_original_aspect_ratio=increase` | `crop=TARGET_W:TOP_H` | Edges cropped |
| FIT (new GAMING_STACKED_FIT) | `force_original_aspect_ratio=decrease` | `pad=...:(ow-iw)/2:...` | Full frame, black bars |

**Why FIT for gaming:** gameplay often has a landscape 16:9 region. When stacked in a 9:16 panel, it will be letterboxed with black bars on the sides. This preserves ALL game content. The user explicitly requested this behavior ("NO QUIERO QUE EL GAMEPLAY SE RECORTE PARA LLENAR LA PANTALLA").

---

## Two Independent Source Branches

The `split=2` filter creates two INDEPENDENT branches from the same source input:
- `[main]` branch: gameplay crop chain  
- `[face]` branch: facecam crop chain

Each branch independently crops and scales its region. No overlay between regions.
The `[face]` branch is NOT derived from `[main]` — both come directly from `[0:v]split=2`.

---

## Blurred Background Variant (bg='blurred')

```
[0:v]split=2[main][face];
[main]crop=GW:GH:GX:GY,split=2[gblu][gfit];
[gblu]scale=1080:TOP_H:force_original_aspect_ratio=increase,crop=1080:TOP_H,boxblur=luma_radius=20:luma_power=3:chroma_radius=20:chroma_power=3[gbg];
[gfit]scale=1080:TOP_H:force_original_aspect_ratio=decrease[gfg];
[gbg][gfg]overlay=(W-w)/2:(H-h)/2[v0];
[face]crop=FW:FH:FX:FY,scale=1080:BOT_H:force_original_aspect_ratio=decrease,pad=1080:BOT_H:(ow-iw)/2:(oh-ih)/2:black[v1];
[v0][v1]vstack=inputs=2[out]
```

The gameplay stream is split again internally:
- `[gblu]` — blurred fill (FILL=increase+crop+blur)
- `[gfit]` — FIT content layer (decrease)
- `overlay` — FIT content centered on blurred background

---

## Caption Safe Zone

When `preset == 'GAMING_STACKED_FIT'`, captions are pushed up into the gameplay panel:
```python
caption_settings["margin_v"] = max(
    int(caption_settings.get("margin_v", 200)),
    TARGET_H - top_h_px + 100,  # 100px buffer above webcam boundary
)
```

For 65/35: `margin_v = max(200, 1920-1248+100) = max(200, 772) = 772px`

---

## Key FFmpeg Flags

- `-map [out]` — output the labeled stream from filter_complex
- `-map 0:a?` — pass audio through unchanged (optional, silent if no audio)
- `force_original_aspect_ratio=decrease` — scale DOWN to fit, never upscale beyond AR
- `pad=W:H:(ow-iw)/2:(oh-ih)/2` — center pad
- `vstack=inputs=2` — vertical stack (top=v0, bottom=v1)
