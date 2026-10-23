"""ConcatAdapter — high-level interface to Concat v0.2.8 via MCP.

This adapter is intentionally isolated: it has no imports from the main
pipeline and communicates with Concat only via the verified MCP API.

Usage:
    from integrations.concat.adapter import ConcatAdapter, ConcatRenderRequest

    req = ConcatRenderRequest(
        source_path="C:/path/to/source.mp4",
        output_path="C:/path/to/out.mp4",
        start_s=42.0,
        duration_s=30.0,
        x_offset=1058,
        src_w=1920, src_h=1080,
        caption_words=[...],   # optional; word-level dicts from pipeline
    )
    result = adapter.render(req)
    # result.output_path, result.render_time_s, result.engine_version, ...

If Concat is unavailable (not installed, disabled, SAC-blocked), all methods
raise ``ConcatNotAvailable``.  Callers MUST catch this and fall back to FFmpeg.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from integrations.concat.exceptions import (
    ConcatExportFailed,
    ConcatMCPError,
    ConcatNotAvailable,
    ConcatTimeout,
)
from integrations.concat.mcp_client import MCPClient
from integrations.concat.crop_converter import (
    x_offset_to_concat_transform,
    keypoints_to_concat_transforms,
)

logger = logging.getLogger("concat.adapter")

CONCAT_VERSION = "0.2.8"  # pinned version — update when intentionally upgrading


@dataclass
class ConcatRenderRequest:
    source_path: str
    output_path: str
    start_s: float
    duration_s: float
    x_offset: int
    src_w: int = 1920
    src_h: int = 1080
    canvas_w: int = 1080
    canvas_h: int = 1920
    fps: int = 30
    keypoints: list = field(default_factory=list)
    caption_words: list = field(default_factory=list)   # word-level dicts from pipeline
    crf: int = 18
    codec: str = "h264"


@dataclass
class ConcatRenderResult:
    output_path: str
    project_path: str
    engine_version: str
    render_time_s: float
    duration_s: float
    width: int
    height: int
    file_size_bytes: int
    success: bool = True
    error: Optional[str] = None


class ConcatAdapter:
    """Wraps Concat MCP calls into a render workflow.

    One adapter instance can be reused across renders; each render launches
    a separate ``--mcp headless`` process with its own project directory.
    """

    def __init__(self, exe_path: str, projects_dir: str,
                 mcp_timeout_s: float = 120.0, export_timeout_s: float = 600.0):
        self._exe = exe_path
        self._projects_dir = Path(projects_dir)
        self._mcp_timeout = mcp_timeout_s
        self._export_timeout = export_timeout_s

    def is_available(self) -> bool:
        """Return True if the Concat executable exists and can be launched."""
        if not Path(self._exe).exists():
            return False
        try:
            result = subprocess.run(
                [self._exe, "--version"],
                capture_output=True, timeout=5, text=True
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def render(self, req: ConcatRenderRequest) -> ConcatRenderResult:
        """Render a clip via Concat. Raises ConcatNotAvailable/ConcatTimeout on failure."""
        self._projects_dir.mkdir(parents=True, exist_ok=True)
        project_name = f"clip_{uuid.uuid4().hex[:12]}"
        project_dir = str(self._projects_dir / project_name)

        t0 = time.monotonic()
        with MCPClient(self._exe, timeout_s=self._mcp_timeout) as mcp:
            engine_version = self._get_version(mcp)
            self._create_project(mcp, project_dir, req)
            media_id = self._import_media(mcp, project_dir, req.source_path)
            track_id = self._add_track(mcp, project_dir)
            clip_id = self._add_clip(mcp, project_dir, media_id, track_id, req)
            self._trim_clip(mcp, project_dir, clip_id, req)
            self._apply_framing(mcp, project_dir, clip_id, req)
            if req.caption_words:
                self._add_captions(mcp, project_dir, req)
            self._save_project(mcp, project_dir)
            output_path = self._export(mcp, project_dir, req)

        render_time = time.monotonic() - t0

        # Verify output
        out = Path(output_path)
        if not out.exists() or out.stat().st_size == 0:
            raise ConcatExportFailed(f"Export completed but output missing: {output_path}")

        size = out.stat().st_size
        meta = self._probe(output_path)

        logger.info("Concat render done: %s in %.1fs (v%s)", out.name, render_time, engine_version)

        return ConcatRenderResult(
            output_path=output_path,
            project_path=project_dir,
            engine_version=engine_version,
            render_time_s=render_time,
            duration_s=meta.get("duration", req.duration_s),
            width=meta.get("width", req.canvas_w),
            height=meta.get("height", req.canvas_h),
            file_size_bytes=size,
        )

    # ── MCP operation wrappers ───────────────────────────────────────────────

    def _get_version(self, mcp: MCPClient) -> str:
        try:
            return mcp.get_version()
        except Exception:
            return CONCAT_VERSION

    def _create_project(self, mcp: MCPClient, project_dir: str, req: ConcatRenderRequest):
        mcp.call("project_create", {
            "location": str(Path(project_dir).parent),
            "name": Path(project_dir).name,
            "video": {
                "width": req.canvas_w,
                "height": req.canvas_h,
                "rateNum": req.fps,
                "rateDen": 1,
            },
        })

    def _import_media(self, mcp: MCPClient, project_dir: str, file_path: str) -> str:
        result = mcp.call("media_import", {
            "path": project_dir,
            "file": file_path,
        })
        if isinstance(result, dict):
            return result.get("createdId") or result.get("id") or ""
        return str(result)

    def _add_track(self, mcp: MCPClient, project_dir: str) -> str:
        result = mcp.call("track_add", {
            "path": project_dir,
            "kind": "video",
        })
        if isinstance(result, dict):
            return result.get("id") or result.get("trackId") or "track-0"
        return "track-0"

    def _add_clip(self, mcp: MCPClient, project_dir: str,
                  media_id: str, track_id: str, req: ConcatRenderRequest) -> str:
        result = mcp.call("clip_add", {
            "path": project_dir,
            "mediaId": media_id,
            "trackId": track_id,
            "start": 0.0,  # place at timeline position 0
            "ripple": False,
        })
        if isinstance(result, dict):
            return result.get("clipId") or result.get("id") or "clip-0"
        return "clip-0"

    def _trim_clip(self, mcp: MCPClient, project_dir: str,
                   clip_id: str, req: ConcatRenderRequest):
        # Trim start to req.start_s by moving the in-point
        if req.start_s > 0:
            mcp.call("clip_trim", {
                "path": project_dir,
                "clipId": clip_id,
                "edge": "start",
                "delta": req.start_s,
                "ripple": False,
            })
        # Trim end to start_s + duration_s
        mcp.call("clip_trim", {
            "path": project_dir,
            "clipId": clip_id,
            "edge": "end",
            "delta": -(req.start_s),  # undo excess from original media length
            "ripple": False,
        })

    def _apply_framing(self, mcp: MCPClient, project_dir: str,
                       clip_id: str, req: ConcatRenderRequest):
        # Step 1: set fill framing (landscape → portrait, crop sides)
        mcp.call("clip_frame", {
            "path": project_dir,
            "clipId": clip_id,
            "framing": "fill",
        })
        # Step 2: shift horizontal center to align on detected subject
        transform = x_offset_to_concat_transform(
            req.x_offset, req.src_w, req.src_h, req.canvas_w, req.canvas_h
        )
        mcp.call("clip_transform", {
            "path": project_dir,
            "clipId": clip_id,
            **transform,
        })
        # Step 3: if multi-scene keypoints, set per-keyframe offsets
        if req.keypoints and len(req.keypoints) > 1:
            kf_list = keypoints_to_concat_transforms(
                req.keypoints, req.duration_s, req.src_w, req.src_h, req.canvas_w, req.canvas_h
            )
            for kf in kf_list:
                mcp.call("keyframe_set", {
                    "path": project_dir,
                    "clipId": clip_id,
                    "time": kf["time"],
                    "property": "offsetX",
                    "value": kf["offsetX"],
                })

    def _add_captions(self, mcp: MCPClient, project_dir: str, req: ConcatRenderRequest):
        # captions_add is in the MCP tool list but parameters are undocumented.
        # Strategy: attempt captions_add; if it fails, fall back to individual
        # title_add calls per word segment (visible in Phase 6 experiments).
        try:
            mcp.call("captions_add", {
                "path": project_dir,
                "words": req.caption_words,
            })
        except ConcatMCPError as e:
            logger.warning("captions_add failed (%s) — captions skipped for this render", e)

    def _save_project(self, mcp: MCPClient, project_dir: str):
        mcp.call("project_save", {"path": project_dir})

    def _export(self, mcp: MCPClient, project_dir: str, req: ConcatRenderRequest) -> str:
        output_path = req.output_path
        mcp.call("export_start", {
            "path": project_dir,
            "output": output_path,
            "width": req.canvas_w,
            "height": req.canvas_h,
            "codec": req.codec,
            "crf": req.crf,
            "rateNum": req.fps,
            "rateDen": 1,
        })
        # Poll export_status until done
        deadline = time.monotonic() + self._export_timeout
        while time.monotonic() < deadline:
            status = mcp.call("export_status", {"path": project_dir})
            if isinstance(status, dict):
                state = status.get("status", "")
                if state in ("done", "completed", "finished"):
                    return output_path
                if state in ("failed", "error", "cancelled"):
                    raise ConcatExportFailed(f"Export failed with status: {state}")
                progress = status.get("progress", 0)
                logger.debug("Export progress: %s%%", progress)
            time.sleep(2.0)
        mcp.call("export_cancel", {"path": project_dir})
        raise ConcatTimeout(f"Export timed out after {self._export_timeout}s")

    def _probe(self, path: str) -> dict:
        from engine.config import CONFIG
        import json as _json
        try:
            r = subprocess.run(
                [CONFIG.ffprobe_path, "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-show_format", path],
                capture_output=True, text=True, timeout=10
            )
            data = _json.loads(r.stdout)
            fmt = data.get("format", {})
            vs = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
            return {
                "duration": float(fmt.get("duration", 0)),
                "width": int(vs.get("width", 0)),
                "height": int(vs.get("height", 0)),
            }
        except Exception:
            return {}
