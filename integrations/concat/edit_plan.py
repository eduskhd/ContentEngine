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
    x_offset: int = 960             # subject center in source pixels (960 = center of 1920)
    crop_preset: Optional[str] = None   # "GAMING_STACKED_FIT" etc.
    keypoints: list = field(default_factory=list)  # [[rel_t, x_offset_px], ...]

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
                """SELECT v.path, v.width, v.height, ca.start_s, ca.end_s
                   FROM candidates ca
                   JOIN videos v ON ca.video_id = v.id
                   WHERE ca.id = ?""",
                (clip["candidate_id"],)
            ).fetchone()

        if not row:
            raise ValueError(f"Cannot resolve source for clip {clip_id}")

        src_path, src_w, src_h, start_s, end_s = row
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

        return cls(
            source_path=str(src_path),
            start_s=float(start_s),
            duration_s=duration_s,
            src_w=int(src_w or 1920),
            src_h=int(src_h or 1080),
            canvas_w=clip.get("width") or 1080,
            canvas_h=clip.get("height") or 1920,
            fps=clip.get("fps") or 30,
            x_offset=960,   # center; caller can override from framing_plan
            caption_enabled=caption_enabled,
            caption_words=caption_words,
            caption_settings=caption_settings,
            render_engine=render_engine,
            edit_method=edit_method,
        )
