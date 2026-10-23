# Concat — Version, API and Windows Compatibility

**Verified:** 2026-10-23  
**Version pinned:** v0.2.8 (released 2026-10-20)  
**Repository:** https://github.com/jub0t/Concat  
**License:** AGPL-3.0

---

## What Concat is

Editor de vídeo nativo multiplataforma escrito en **Rust** con compositor GPU (wgpu).  
No es una librería ni un CLI puro — es una aplicación de escritorio con GUI propia (Slint),  
pero con un **MCP server headless** que permite operación completamente automatizada sin GUI.  
Internamente usa FFmpeg 7+ para decodificación/codificación pero expone su propia API de edición de alto nivel.

Stack: Rust 1.93+, cargo workspace, FFmpeg 7+ como dependencia de sistema.

---

## Windows Installers (v0.2.8)

| File | Type |
|------|------|
| `concat-0.2.8-windows-x86_64-setup.exe` | Installer |
| `concat-0.2.8-windows-x86_64.msi` | MSI |

**Default install path:** `%LOCALAPPDATA%\Programs\Concat\concat.exe`  
**Config path:** `concat_exe_path` in `engine/config.py`

---

## CRITICAL — Smart App Control (SAC) Risk

The Concat binary is **unsigned** (no code-signing certificate).  
On Windows 11 with Smart App Control in **"on" mode** (not "evaluation"),  
the executable will be blocked completely — same mechanism as `libmediapipe.dll`.

**Verification required before installing:**
```powershell
# Check SAC policy state
Get-MpComputerStatus | Select-Object SmartAppControlState
# States: "On" (blocks unsigned), "Evaluation" (may allow), "Off" (no block)
```

If SAC is "On": only option is compile from source with Rust toolchain, or request a Microsoft policy exception.

---

## MCP API — Headless Mode

```powershell
concat.exe --mcp headless    # no GUI, one project at a time (uses concat.lock)
concat.exe --mcp window      # attached to open window
concat.exe --mcp auto        # automatic selection (default)
```

**Protocol:** MCP stdio, JSON-RPC 2.0 newline-delimited  
**Request format:**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"<tool>","arguments":{...}}}
```

**Environment variables:**
- `CONCAT_API_ADDRESS` — remote server (e.g. `127.0.0.1:7420`)
- `CONCAT_API_TOKEN` — authentication token
- `CONCAT_MCP_ROOTS` — additional allowed folders (`;`-separated on Windows)

---

## Verified MCP Tools

### Projects
| Tool | Key Arguments |
|------|--------------|
| `project_create` | `location`, `name`, `video: {width, height, rateNum, rateDen}` |
| `project_open` | `path` |
| `project_save` | `path` |
| `project_close` | `path` |
| `project_list` | — |
| `project_set_video` | `path`, `video` |
| `project_get` | `path` |

### Media
| Tool | Key Arguments |
|------|--------------|
| `media_import` | `path` (project dir), `file` (video file) → returns `createdId` |
| `media_probe` | `file` |

### Timeline / Clips
| Tool | Key Arguments |
|------|--------------|
| `track_add` | `path`, `kind: "video"\|"audio"` → returns `id` |
| `clip_add` | `path`, `mediaId`, `trackId`, `start` (seconds), `ripple` |
| `clip_trim` | `path`, `clipId`, `edge: "start"\|"end"`, `delta` (signed seconds), `ripple` |
| `clips_split` | `path`, `clipId`, `time` |
| `clips_move` | `path`, `clipId`, `time`, `trackId`, `ripple` |
| `clips_remove` | `path`, `clipId`, `ripple` |
| `clip_update` | `path`, `clipId`, `patch: {crop: {left,top,right,bottom}}` |
| `clip_transform` | `path`, `clipId`, `scale`, `offsetX`, `offsetY`, `rotation` |
| `clip_frame` | `path`, `clipId`, `framing: "fit"\|"fill"` |
| `clip_speed` | `path`, `clipId`, `speed` |
| `clip_stabilize` | `path`, `clipId` |
| `clip_mask` | `path`, `clipId`, `...` |

### Text & Captions
| Tool | Key Arguments |
|------|--------------|
| `title_add` | `path`, `trackId`, `start`, `duration`, `offsetY`, `style: {fontSize, fontFamily, color, strokeColor, align, background}` |
| `captions_add` | `path`, `words` — **parameters NOT documented in API reference** |

### Keyframes & Effects
| Tool | Key Arguments |
|------|--------------|
| `keyframe_set` | `path`, `clipId`, `time`, `property`, `value` |
| `keyframe_clear` | `path`, `clipId`, `property` |
| `effects_list` | `path` |
| `effect_layer_add` | `path`, `clipId`, `effect` |
| `effect_key_set` | `path`, `clipId`, `effect`, `property`, `time`, `value` |

### Export
| Tool | Key Arguments |
|------|--------------|
| `export_start` | `path`, `output`, `width`, `height`, `codec: "h264"\|"hevc"\|"av1"`, `crf` (0–63), `rateNum`, `rateDen` |
| `export_status` | `path` → returns `{status, progress}` |
| `export_wait` | `path` |
| `export_cancel` | `path` |

---

## Export Settings for Content Engine

```json
{
  "width": 1080,
  "height": 1920,
  "codec": "h264",
  "crf": 18,
  "rateNum": 30,
  "rateDen": 1
}
```

1080×1920 portrait confirmed supported via `VideoSettings`.

---

## Crop Model

Concat crop uses **fractions of each edge removed** (not pixels):
```json
{"left": 0.1, "top": 0.0, "right": 0.1, "bottom": 0.0}
```
- Range: 0.0 to 0.9 per edge, minimum 10% of image must remain
- For landscape→portrait conversion: use `clip_frame: "fill"` + `clip_transform.offsetX`

`offsetX` unit: **frame fractions** (1.0 = one full canvas width = 1080px)  
Documented range: ±3

---

## Known Issues and Limitations

| Issue | Severity | Status |
|-------|----------|--------|
| Unsigned binary — SAC blocks on some Windows 11 | **CRITICAL** | Unresolved v0.2.8 |
| GPU blur/glow export stalls | HIGH | Unresolved v0.2.7, v0.2.8 NOT CONFIRMED |
| Direct3D 11 crash on some systems (#480) | HIGH | Open issue |
| `captions_add` parameters undocumented | MEDIUM | In MCP list, not in API docs |
| No pixel-based crop (only fractional edges) | MEDIUM | By design — needs conversion |
| `concat.lock` — one headless process per project | LOW | By design |
| Simultaneous GUI+MCP editing not supported | LOW | Planned #337 |

---

## Headless Operation

**Confirmed.** `concat.exe --mcp headless` runs without GUI or display.  
Each project directory gets a `concat.lock` file — multiple headless processes must use separate project directories.  
Content Engine workers must create one project dir per clip render.
