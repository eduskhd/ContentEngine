# EditPlan Specification — Phase 7

**Status:** DRAFT — pending Concat installation and Phase 6 experiments  
**Last updated:** 2026-10-23

---

## Purpose

An `EditPlan` is a motor-independent description of a clip render operation.  
The same plan can be translated to FFmpeg commands or Concat MCP calls.

---

## Schema (draft)

```python
@dataclass
class EditPlan:
    # Source
    source_path: str
    start_s: float
    duration_s: float

    # Video
    src_w: int = 1920
    src_h: int = 1080
    canvas_w: int = 1080
    canvas_h: int = 1920
    fps: int = 30

    # Crop / Layout
    framing: str = "fill"           # "fill" | "fit" | "manual"
    x_offset: int = 960             # subject center in source pixels
    crop_preset: str | None = None  # "GAMING_STACKED_FIT" etc.
    keypoints: list = field(default_factory=list)   # [[rel_t, x_off], ...]

    # Captions
    caption_enabled: bool = True
    caption_words: list = field(default_factory=list)   # word-level dicts
    caption_settings: dict = field(default_factory=dict)  # preset settings

    # Export
    codec: str = "h264"
    crf: int = 18
    render_engine: str = "ffmpeg"   # "ffmpeg" | "concat"

    # Metadata
    edit_method: str = "pipeline_auto"  # "pipeline_auto" | "manual" | "experimental"
```

---

## Translators (Phase 7 implementation)

### FFmpeg (existing)

The current `render_clip.py` `_render_one()` function is the FFmpeg translator.  
No changes to this path — it continues to be the primary renderer.

### Concat (to be implemented)

`integrations/concat/adapter.py` `ConcatAdapter.render()` takes a `ConcatRenderRequest`,  
which maps 1:1 from `EditPlan` fields.

Mapping table:

| EditPlan field | Concat operation |
|---------------|-----------------|
| `source_path` | `media_import.file` |
| `start_s` | `clip_trim(edge="start", delta=start_s)` |
| `duration_s` | `clip_trim(edge="end", ...)` |
| `canvas_w/h` | `project_create.video.{width,height}` |
| `fps` | `project_create.video.{rateNum,rateDen}` |
| `framing` | `clip_frame.framing` |
| `x_offset` | `clip_transform.offsetX` via `crop_converter` |
| `keypoints` | `keyframe_set` calls per keypoint |
| `caption_words` | `captions_add.words` (or `title_add` fallback) |
| `codec` | `export_start.codec` |
| `crf` | `export_start.crf` |

---

## Serialization

`EditPlan` instances are serialized to JSON and stored in:
- `clip_variants.edit_plan_json` — the exact plan used for this render
- `jobs.metadata["edit_plan"]` — the plan submitted with the job

This allows re-rendering: deserialize from `edit_plan_json`, update `render_engine`, re-render.

---

## Implementation note

`EditPlan` will be implemented in `integrations/concat/edit_plan.py` during Phase 7,  
after verifying Concat operations in Phase 6 experiments.  
The FFmpeg path does NOT require EditPlan — it remains unchanged.
