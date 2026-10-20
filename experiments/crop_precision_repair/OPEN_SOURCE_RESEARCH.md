# Open Source Research — Crop Precision Repair
**Date:** 2026-10-20  
**Purpose:** Evaluate 8 repositories for relevance to fixing the manual crop coordinate mismatch between New Job rectangle selection and final MP4 output.

**Decision criteria:** Does this library concretely improve coordinate precision, canvas interaction, or layout quality? Not: does it do something impressive in general.

---

## 1. Konva.js
**Repo:** https://github.com/konvajs/konva

| Field | Value |
|---|---|
| License | MIT |
| Maintenance | Actively maintained — 4,192 commits, npm weekly downloads in millions |
| Language | TypeScript/JavaScript |
| Package size | ~100 KB minified+gzip |
| Dependencies | Zero runtime dependencies |

### What it actually does
Konva is a scene-graph canvas library. It wraps the HTML5 canvas API and adds:
- Named, selectable shapes (Rect, Circle, Line, Image, etc.) with pixel-coordinate positions
- Per-shape drag, resize (Transformer), and event handling
- Layer system for draw-order control
- DPR handling: Stage internally scales the canvas buffer by `window.devicePixelRatio` and corrects pointer coordinates via `scaleX = rect.width / content.clientWidth`. User-space coordinates are always CSS pixels.

### DPR behavior (critical for our problem)
Konva's Stage computes `_getContentPosition()` as:
```
scaleX = rect.width / content.clientWidth  (≈ devicePixelRatio on HiDPI)
scaleY = rect.height / content.clientHeight
```
These are applied to every pointer event, so pointer coordinates returned by Konva event handlers are **CSS-pixel-space** (not physical pixels). This is the same space the underlying `<canvas>` element's CSS dimensions occupy. Konva does NOT automatically output coordinates in image-pixel space — you must convert manually from CSS pixels to image pixels.

### Coordinate representation
- All shape positions: CSS pixel `x, y` from top-left of the Stage.
- No built-in normalized [0-1] representation; you compute `norm_x = shape.x() / stage.width()`.
- Transformer handles (resize handles) emit the new shape bounds in the same CSS-pixel space.

### Benefits for our pipeline
- The Transformer widget provides polished 8-handle resize UX with drag, that the current vanilla canvas implementation replicates manually.
- Konva's `scaleX/scaleY` correction in pointer events is more robust than our current `(e.clientX - rect.left) * canvas.width / rect.width` — same math, but battle-tested.
- Two independent `Rect` shapes on a single `Stage` would replace the current `_njUrlCropState.gameplay / facecam` state with named objects.

### Limitations
- JS-only; no Python side.
- Does not know the video's natural dimensions — you still have to normalize output coords yourself.
- Does not solve the root-cause bug (renderer uses wrong source dimensions for denormalization).
- Adding Konva adds ~100 KB to the bundle and a new dependency for a UI that already works.

### Integration cost: LOW-MEDIUM
Replace the current `<canvas>` pointer event handlers (~300 lines) with a Konva Stage + two Rect shapes + one Transformer. The normalization logic stays the same.

### Verdict
**Useful only if the canvas selector needs a replacement.** Konva would improve UX polish (resize handles, smoother drag) but does not fix the coordinate math bug. If the current selector is kept and the renderer bug is fixed, Konva adds no value.

---

## 2. Cropper.js
**Repo:** https://github.com/fengyuanchen/cropperjs

| Field | Value |
|---|---|
| License | MIT |
| Maintenance | Active — v2 in development on `main` branch, v1 stable |
| Language | JavaScript |
| Dependencies | Zero |
| Video support | No — works on `<img>` and `<canvas>` elements only |

### What it actually does
A single-crop-box UI widget for images. Provides `getData()` which returns coordinates in the **natural image pixel space** (not CSS pixel space) — this is its primary advantage over naive canvas implementations.

The data contract: `{ x, y, width, height, rotate, scaleX, scaleY }` where x/y/width/height are in the original image's pixel dimensions regardless of display zoom or DPR.

### Coordinate representation
`getData()` accounts for the displayed-vs-natural size ratio internally. The return values are in natural pixels — directly usable as FFmpeg crop coordinates if the image matches the source video resolution.

### Benefits for our pipeline
- Automatic natural-pixel output eliminates one source of coordinate drift.
- Built-in aspect-ratio locking option.
- Well-tested crop-box to image-pixel math.

### Limitations
- **Single crop box only.** Our use case requires two independent regions (gameplay + webcam). Cropper.js v1/v2 does not support multiple independent crop boxes.
- Works on `<img>` only — cannot crop directly on a `<canvas>` or `<video>`.
- Would require significant adaptation: run two separate Cropper instances on two separate `<img>` elements, coordinate state manually.
- Does not solve the renderer denormalization bug.

### Integration cost: MEDIUM-HIGH
Cannot drop-in replace the current two-region canvas. Would require a two-instance approach with synthetic images, adding complexity without equivalent gain over fixing the existing canvas code.

### Verdict
**Not recommended.** The single-box limitation makes it a poor fit. The only benefit (natural-pixel coordinates) is achievable by fixing the renderer's denormalization to use actual source dimensions — a 2-line fix.

---

## 3. FFmpeg — crop filter
**Repo:** https://github.com/FFmpeg/FFmpeg

| Field | Value |
|---|---|
| License | LGPL 2.1+ / GPL 2+ |
| Maintenance | Actively maintained |

### crop filter coordinate space
The FFmpeg `crop` filter operates in **coded pixel space** — the raw decoded frame dimensions as reported by ffprobe's `width` and `height` fields for the video stream. It does NOT apply SAR (Sample Aspect Ratio) correction.

Key: for most YouTube/gaming content (H.264, 1920×1080 SAR 1:1), coded pixels = display pixels. For legacy content with non-square pixels (some MPEG-2, DVDs, older camcorder formats), they differ.

### Relevant filter syntax for split-layout compositing
```
[0:v]split=2[a][b];
[a]crop=W:H:X:Y,scale=1080:top_h[v0];
[b]crop=W:H:X:Y,scale=1080:bot_h:force_original_aspect_ratio=decrease,pad=1080:bot_h:(ow-iw)/2:(oh-ih)/2[v1];
[v0][v1]vstack=inputs=2[out]
```

All coordinates (W, H, X, Y) are in coded pixel space of the INPUT stream, not the output.

### Integration note
The existing pipeline already uses FFmpeg filter_complex correctly. The crop filter math is fine; the bug is upstream (wrong pixel values passed in).

### Verdict
**No change needed.** FFmpeg is already the correct tool and is used correctly.

---

## 4. PySceneDetect
**Repo:** https://github.com/Breakthrough/PySceneDetect

| Field | Value |
|---|---|
| License | BSD-3-Clause |
| Maintenance | Actively maintained, Python 3.10–3.13 supported |
| Windows | Yes (MSI installer + pip) |
| Dependencies | opencv-python (bundled), optional ffmpeg |
| Output | Timestamps + frame numbers |

### What it actually does
Detects scene cuts in video files using three algorithms:
- `ContentDetector` — detects fast cuts via HSV histogram difference
- `AdaptiveDetector` — detects gradual transitions / camera movement
- `ThresholdDetector` — detects fade-to-black

Returns a `SceneList` with start/end `FrameTimecode` objects. Can call `split_video_ffmpeg()` to cut the source file at scene boundaries.

### Benefits for our pipeline
- Could detect when a gaming video changes from "gameplay + facecam" to "fullscreen cutscene" — alerting the user that the manual crop config may not apply to all segments.
- Could be used to validate that a single crop config is appropriate for the entire clip window.

### Limitations
- Not a reframing tool — gives you cut points, not crop coordinates.
- Adding it requires Python 3.10+ (already satisfied) and OpenCV (already used by reframer).
- The smart-reframing pipeline already runs a proxy for visual analysis; PySceneDetect would be a useful addition there, not a replacement.

### Integration cost: LOW
`pip install scenedetect-headless` (~8 MB). Drop-in function call after proxy generation. No architectural change needed.

### Verdict
**Potentially useful as an enhancement** — flagging crop config incompatibility across scene changes. Not relevant to fixing the current coordinate precision bug.

---

## 5. MediaPipe
**Repo:** https://github.com/google-ai-edge/mediapipe

| Field | Value |
|---|---|
| License | Apache 2.0 |
| Maintenance | Actively maintained by Google |
| Windows | Yes (22.8 MB wheel, x86-64 and ARM64) |
| Python | 3.9–3.14 |
| Package size | 22.8 MB (Windows) |
| GPU | Optional — runs on CPU |

### What it actually does
MediaPipe Tasks provides pre-built ML pipelines for face detection, face landmark, pose landmark, hand landmark, object detection, and image segmentation. For video analysis:
- `FaceDetector`: bounding box + 6 keypoints per face, coordinates in **normalized [0-1] space** relative to frame dimensions
- `FaceLandmarker`: 478 3D landmarks per face, also normalized
- All detectors can process video files frame-by-frame

### Benefits for our pipeline
The existing face/gameplay detection in `engine/analyzers/visual_analyzer.py` could be enhanced or replaced with MediaPipe for more accurate face bounding boxes. This would improve automatic crop proposals, not fix the manual crop coordinate precision.

### Limitations
- 22.8 MB dependency for face detection that's already partially working.
- Returns normalized coords — still needs denormalization to video pixel space (same challenge as our current bug).
- Overkill for the stated problem (manual rectangle accuracy).

### Integration cost: LOW (pip install mediapipe) — MEDIUM (integration into visual_analyzer.py)

### Verdict
**Useful for improving auto-detection proposals, not for fixing manual crop precision.** If the auto-detection quality needs improvement, MediaPipe is the right tool. Out of scope for the current bug.

---

## 6. auto-video-editor
**Repo:** https://github.com/kiy0ni/auto-video-editor

| Field | Value |
|---|---|
| License | MIT |
| Maintenance | Low — 12 commits, 6 stars, small user base |
| Language | Python 3.9+ |
| Dependencies | FFmpeg, faster-whisper/OpenAI Whisper, OpenCV (optional) |

### What it actually does
Converts long recordings into short vertical clips. Key capabilities:
- Sentence-boundary cut detection (via Whisper transcript)
- Four vertical layout modes: `blur`, `crop`, `smart` (OpenCV face tracking), `split` (webcam overlay detection)
- Single FFmpeg filter graph per output (trim + layout + captions + loudness normalization)
- Hardware encoding support (NVENC, QSV, VideoToolbox)

The `smart` layout uses OpenCV Haar cascades for face detection, falls back to center crop if no face found. The `split` layout auto-detects webcam overlays by scanning frame regions.

### Architecture similarity to ContentEngine
Very close: both use a single FFmpeg filter_complex pass, hardware encoding with software fallback, faster-whisper for transcription, and a proxy/analysis phase before rendering. The webcam overlay detection approach (`split` mode) is relevant.

### Benefits for our pipeline
- The webcam overlay detection algorithm is worth reading — uses frame sampling + region-of-interest analysis to locate the facecam automatically.
- The single-pass FFmpeg approach with ASS captions is already what ContentEngine does.

### Limitations
- 6 stars, 12 commits — not production-tested at scale.
- No JavaScript/browser component — only a CLI.
- Does not provide a manual crop UI.
- Face tracking quality is OpenCV Haar-cascade level (2010 tech), worse than existing reframer.

### Integration cost: N/A — not directly importable as a library, would require reading and adapting its webcam detection code.

### Verdict
**No integration recommended.** The webcam detection code is interesting to read for inspiration; do not import the library.

---

## 7. hypecut
**Repo:** https://github.com/Yu-0312/hypecut

| Field | Value |
|---|---|
| License | Apache-2.0 |
| Maintenance | Active development (roadmap present, contributions welcome), 14 commits |
| Language | Python 3.10+ |
| Dependencies | FFmpeg, optional CLIP/Whisper/yt-dlp |

### What it actually does
Automated highlight reel generator for gameplay VODs. Detects highlights via multiple signals (audio energy, score changes, chat activity if available), ranks clips, and stitches them. Also supports:
- `--reframe-track`: vertical/square crop with motion tracking
- `--reframe stack`: facecam detection + stacking layout
- Multi-aspect-ratio rendering from one analysis pass

### Benefits for our pipeline
The `--reframe stack` feature with facecam detection is architecturally similar to ContentEngine's gaming mode. The highlight scoring approach is relevant to virality detection.

### Limitations
- 14 commits — not battle-tested.
- Separate CLI tool, not a library. Importing its internals would require significant adaptation.
- Highlight detection and reframing are already implemented in ContentEngine.
- No browser/frontend component.

### Integration cost: HIGH (would need to extract and adapt internal modules)

### Verdict
**No integration recommended.** Interesting as a reference architecture. The multi-signal highlight scoring is worth reviewing conceptually; do not integrate as a dependency.

---

## 8. reframe
**Repo:** https://github.com/vxnuaj/reframe

| Field | Value |
|---|---|
| License | Not specified in repo |
| Maintenance | 0 stars, 0 watchers, 7 commits — essentially a personal prototype |
| Language | Python |
| Dependencies | YOLO, MediaPipe, OpenCV, scenedetect, PyTorch (ML extra) |

### What it actually does
Multi-stage video reframing pipeline: scene detection → YOLO+ByteTrack object tracking → speaker identification (lip motion) → spring-based virtual camera → JSON crop path output. The output is a keyframe JSON with `{center_x, center_y, zoom}` values that a renderer applies to the source.

### Benefits for our pipeline
- The separation of analysis (JSON crop path) from rendering is a clean architectural pattern.
- Spring-based camera damping for smooth crop transitions is worth implementing for auto-detection mode.

### Limitations
- Zero community adoption, no license.
- Heavy ML dependency stack (PyTorch, YOLO) — adds GB of dependencies for a prototype.
- Only auto-detection, no manual override.
- No tests, no documentation beyond README.

### Integration cost: HIGH + LICENSE RISK (no license stated)

### Verdict
**Do not integrate.** No license, no production validation, excessive dependencies. The JSON crop path idea is architecturally sound but can be implemented without this library.

---

## Summary Table

| Library | License | Our Problem? | Integrate? | Cost |
|---|---|---|---|---|
| Konva.js | MIT | Improves canvas UX (not the root cause) | Only if selector is replaced | Low-Med |
| Cropper.js | MIT | No — single-box only | No | — |
| FFmpeg crop | LGPL/GPL | Already correct — no change needed | No | — |
| PySceneDetect | BSD-3 | Adjacent — scene change alerts | Maybe later | Low |
| MediaPipe | Apache 2.0 | Adjacent — better auto-detection | Maybe later | Low-Med |
| auto-video-editor | MIT | Read for inspiration only | No | — |
| hypecut | Apache-2.0 | Read for inspiration only | No | — |
| reframe | None | No — no license, prototype | No | — |

---

## Recommendation

**The coordinate mismatch bug does not require any new library.**

The root cause (confirmed by code audit) is that the renderer denormalizes canvas coordinates using the frame-preview resolution (720p from yt-dlp format `bestvideo[height<=720]`) instead of the actual downloaded video resolution (1080p from format `bestvideo[height<=1080]`). This is a 2-line fix in `engine/renderers/render_clip.py`.

The canvas selector itself is geometrically correct — it normalizes to [0-1] relative to the displayed image, which is what we want. The bug is entirely downstream.

**If** the canvas selector is later deemed to need replacement for UX reasons (e.g., adding aspect-ratio locking, better handle UX), **Konva.js** is the recommended choice: MIT licensed, zero dependencies, battle-tested DPR correction, straightforward integration.

**PySceneDetect** and **MediaPipe** are worth evaluating later to improve the auto-detection pipeline (scene change alerts, better face detection proposals). Neither is needed for the current precision fix.
