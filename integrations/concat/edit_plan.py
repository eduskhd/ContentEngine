"""EditPlan — motor-independent description of a clip render operation.

The same plan can drive either the FFmpeg renderer or the Concat adapter.
This module defines the dataclass, constructors, and the Concat translator.

The FFmpeg path is NOT changed — it continues to use render_clip.py directly.
EditPlan is used when Concat is the target engine (concat_enabled=True).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class EditPlan:
    # Source
    source_path: str
    start_s: float
    duration_s: float

    # Video geometry
    src_w: int = 1920
    src_h: int = 1080
    canvas_w: int = 1080
    canvas_h: int = 1920
    fps: int = 30

    # Crop / Layout
    framing: str = "fill"           # "fill" | "fit" | "manual"
    x_offset: int = 656             # left edge of 9:16 crop window in source px (656 = center for 1920w)
    crop_preset: Optional[str] = None   # "GAMING_STACKED_FIT" etc.
    keypoints: list = field(default_factory=list)  # [[rel_t, x_offset_px], ...]

    # Gaming Stacked regions (source pixels, [x, y, w, h]).
    # main_region = gameplay (top panel), secondary_region = webcam (bottom panel).
    # Only set when crop_preset is a GAMING_STACKED variant.
    main_region: Optional[list] = None
    secondary_region: Optional[list] = None
    gaming_top_ratio: float = 0.65   # split fraction: gameplay panel height / total height

    # Captions
    caption_enabled: bool = True
    caption_words: list = field(default_factory=list)   # word-level dicts from transcript
    caption_settings: dict = field(default_factory=dict)  # preset settings

    # Export
    codec: str = "h264"
    crf: int = 18
    render_engine: str = "ffmpeg"   # "ffmpeg" | "concat"

    # Traceability
    edit_method: str = "pipeline_auto"  # "pipeline_auto" | "manual" | "experimental"

    # ── Serialization ────────────────────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> "EditPlan":
        return cls(**json.loads(s))

    # ── Concat translation ───────────────────────────────────────────────────

    def to_concat_request(self):
        """Translate to ConcatRenderRequest.  Raises ImportError if unavailable."""
        from integrations.concat.adapter import ConcatRenderRequest
        return ConcatRenderRequest(
            source_path=self.source_path,
            output_path="",            # caller sets output_path after construction
            start_s=self.start_s,
            duration_s=self.duration_s,
            x_offset=self.x_offset,
            src_w=self.src_w,
            src_h=self.src_h,
            canvas_w=self.canvas_w,
            canvas_h=self.canvas_h,
            fps=self.fps,
            keypoints=self.keypoints,
            caption_words=self.caption_words if self.caption_enabled else [],
            crf=self.crf,
            codec=self.codec,
            crop_preset=self.crop_preset,
            main_region=self.main_region,
            secondary_region=self.secondary_region,
            gaming_top_ratio=self.gaming_top_ratio,
        )

    # ── Constructors ─────────────────────────────────────────────────────────

    @classmethod
    def from_clip(
        cls,
        clip_id: str,
        render_engine: str = "concat",
        edit_method: str = "experimental",
        caption_enabled: bool = True,
    ) -> "EditPlan":
        """Build an EditPlan from a clip row + its candidate + source video.

        Reads from the DB. Raises ValueError if clip or source not found.
        """
        from engine.database import get_clip, db
        import json as _json
        from pathlib import Path

        clip = get_clip(clip_id)
        if not clip:
            raise ValueError(f"Clip not found: {clip_id}")

        with db() as conn:
            row = conn.execute(
                """SELECT v.path, v.width, v.height, ca.start_s, ca.end_s, ca.framing_plan
                   FROM candidates ca
                   JOIN videos v ON ca.video_id = v.id
                   WHERE ca.id = ?""",
                (clip["candidate_id"],)
            ).fetchone()

        if not row:
            raise ValueError(f"Cannot resolve source for clip {clip_id}")

        src_path, src_w, src_h, start_s, end_s, framing_plan_json = row
        if not src_path or not Path(src_path).exists():
            raise ValueError(f"Source video not on disk: {src_path}")

        duration_s = float(end_s or 0) - float(start_s or 0)
        if duration_s <= 0:
            raise ValueError(f"Invalid clip duration for {clip_id}")

        # Recover caption words from clip.caption_data
        caption_words = []
        try:
            cap_data = clip.get("caption_data")
            if isinstance(cap_data, str):
                cap_data = _json.loads(cap_data)
            if cap_data and isinstance(cap_data.get("words"), list):
                caption_words = cap_data["words"]
        except Exception:
            pass

        caption_settings = {}
        try:
            cs = clip.get("caption_settings")
            if isinstance(cs, str):
                cs = _json.loads(cs)
            if cs:
                caption_settings = cs
        except Exception:
            pass

        # Read x_offset from candidate framing_plan.
        # framing_plan.x_offset = LEFT EDGE of the 9:16 crop window in source pixels
        # (same convention as FFmpeg crop=w:h:x:y and crop_converter.py).
        # Default: center crop left edge = (src_w - crop_w) // 2 = (1920 - 607) // 2 = 656
        _src_w = int(src_w or 1920)
        _src_h = int(src_h or 1080)
        _crop_w = int(_src_h * 1080 / 1920)  # source pixels visible at 9:16
        x_offset = (_src_w - _crop_w) // 2   # default: center
        try:
            if framing_plan_json:
                fp = _json.loads(framing_plan_json) if isinstance(framing_plan_json, str) else framing_plan_json
                raw_x = fp.get("x_offset")
                if raw_x is not None:
                    x_offset = int(raw_x)  # already in source px, crop left edge
        except Exception:
            pass

        # Read gaming layout from crop_configs (keyed by job_id).
        # crop_configs stores normalized gameplay/facecam regions (0.0–1.0).
        main_region = None
        secondary_region = None
        crop_preset = None
        gaming_top_ratio = 0.65
        try:
            job_id = clip.get("job_id")
            if job_id:
                from engine.database import get_crop_config
                cc = get_crop_config(job_id)
                if cc and cc.get("gameplay_x") is not None and cc.get("facecam_x") is not None:
                    main_region = [
                        cc["gameplay_x"] * _src_w,
                        cc["gameplay_y"] * _src_h,
                        cc["gameplay_w"] * _src_w,
                        cc["gameplay_h"] * _src_h,
                    ]
                    secondary_region = [
                        cc["facecam_x"] * _src_w,
                        cc["facecam_y"] * _src_h,
                        cc["facecam_w"] * _src_w,
                        cc["facecam_h"] * _src_h,
                    ]
                    crop_preset = cc.get("layout_preset") or "GAMING_STACKED_FIT"
                    gaming_top_ratio = float(cc.get("split_fraction") or 0.65)
        except Exception:
            pass

        return cls(
            source_path=str(src_path),
            start_s=float(start_s),
            duration_s=duration_s,
            src_w=_src_w,
            src_h=_src_h,
            canvas_w=clip.get("width") or 1080,
            canvas_h=clip.get("height") or 1920,
            fps=clip.get("fps") or 30,
            x_offset=x_offset,
            crop_preset=crop_preset,
            main_region=main_region,
            secondary_region=secondary_region,
            gaming_top_ratio=gaming_top_ratio,
            caption_enabled=caption_enabled,
            caption_words=caption_words,
            caption_settings=caption_settings,
            render_engine=render_engine,
            edit_method=edit_method,
        )
