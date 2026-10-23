"""ConcatAdapter — high-level interface to Concat v0.2.8 via concat-cli JSON-RPC API.

This adapter is intentionally isolated: it has no imports from the main
pipeline and communicates with Concat only via the verified JSON-RPC API.

Usage:
    from integrations.concat.adapter import ConcatAdapter, ConcatRenderRequest

    req = ConcatRenderRequest(
        source_path="C:/path/to/source.mp4",
        output_path="C:/path/to/out.mp4",
        start_s=42.0,
        duration_s=30.0,
        x_offset=1058,
        src_w=1920, src_h=1080,
    )
    result = adapter.render(req)

If Concat is unavailable (not installed, disabled), all methods raise
``ConcatNotAvailable``.  Callers MUST catch this and fall back to FFmpeg.

Implementation note: uses concat-cli (headless CLI) with the JSON-RPC API
instead of concat --mcp headless, avoiding the heavy Slint/Skia build.
The underlying Concat API is identical; only the transport differs.
"""
from __future__ import annotations

import json as _json
import logging
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
from integrations.concat.api_client import APIClient, _extract_result
from integrations.concat.crop_converter import (
    x_offset_to_concat_transform,
    keypoints_to_concat_transforms,
)

logger = logging.getLogger("concat.adapter")

CONCAT_VERSION = "0.2.8"


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
    caption_words: list = field(default_factory=list)
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
    """Renders a clip via concat-cli JSON-RPC API.

    Each render creates a fresh project directory.  Two subprocess invocations
    are used: Phase 1 imports the source video to discover its duration (needed
    for precise tail-trim), Phase 2 builds and exports the final clip.
    """

    def __init__(self, cli_path: str, projects_dir: str,
                 api_timeout_s: float = 120.0, export_timeout_s: float = 600.0):
        self._cli = cli_path
        self._projects_dir = Path(projects_dir)
        self._api_timeout = api_timeout_s
        self._export_timeout = export_timeout_s

    def is_available(self) -> bool:
        if not Path(self._cli).exists():
            return False
        try:
            from integrations.concat.api_client import _build_env
            result = subprocess.run(
                [self._cli, "--version"],
                capture_output=True, timeout=5, text=True,
                env=_build_env(),
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def render(self, req: ConcatRenderRequest) -> ConcatRenderResult:
        """Render a clip. Raises ConcatNotAvailable/ConcatTimeout on failure."""
        if not Path(self._cli).exists():
            raise ConcatNotAvailable(f"concat-cli not found: {self._cli}")

        self._projects_dir.mkdir(parents=True, exist_ok=True)
        project_name = f"clip_{uuid.uuid4().hex[:12]}"
        project_parent = str(self._projects_dir).replace("\\", "\\\\")
        project_dir = str(self._projects_dir / project_name)
        project_dir_api = project_dir.replace("\\", "\\\\")
        source_api = req.source_path.replace("\\", "\\\\")

        t0 = time.monotonic()
        client_api = APIClient(self._cli, timeout_s=self._api_timeout)
        client_export = APIClient(self._cli, timeout_s=self._export_timeout)

        # ── Phase 1: create project + import media ─────────────────────────────
        p1_reqs = [
            {
                "jsonrpc": "2.0", "id": 1, "method": "project.create",
                "params": {
                    "location": str(self._projects_dir),
                    "name": project_name,
                    "video": {
                        "width": req.canvas_w,
                        "height": req.canvas_h,
                        "rateNum": int(req.fps),
                        "rateDen": 1,
                    },
                },
            },
            {
                "jsonrpc": "2.0", "id": 2, "method": "media.import",
                "params": {"path": project_dir, "file": req.source_path},
            },
            {
                "jsonrpc": "2.0", "id": 3, "method": "project.save",
                "params": {"path": project_dir},
            },
        ]
        r1 = client_api.run_batch(p1_reqs)

        _extract_result(r1, 1, "project.create")
        import_result = _extract_result(r1, 2, "media.import")
        _extract_result(r1, 3, "project.save")

        media_id = import_result.get("createdId") or "m1"
        media_dur = _get_media_duration(import_result, media_id)
        track_id = _get_default_track(import_result)

        logger.debug("Phase1 done: media=%s dur=%.2fs track=%s", media_id, media_dur, track_id)

        # ── Phase 2: edit + export ──────────────────────────────────────────────
        clip_id = "c1"

        head_delta = req.start_s
        if media_dur and media_dur > 0:
            tail_excess = media_dur - req.start_s - req.duration_s
        else:
            tail_excess = 0.0

        transform = x_offset_to_concat_transform(
            req.x_offset, req.src_w, req.src_h, req.canvas_w, req.canvas_h
        )

        p2_reqs: list[dict] = [
            {
                "jsonrpc": "2.0", "id": 1, "method": "project.open",
                "params": {"path": project_dir},
            },
            {
                "jsonrpc": "2.0", "id": 2, "method": "edit.apply",
                "params": {
                    "path": project_dir,
                    "command": {
                        "op": "addClip",
                        "mediaId": media_id,
                        "trackId": track_id,
                        "start": 0.0,
                    },
                },
            },
        ]
        next_id = 3

        if head_delta > 0:
            p2_reqs.append({
                "jsonrpc": "2.0", "id": next_id, "method": "edit.apply",
                "params": {
                    "path": project_dir,
                    "command": {"op": "trimClip", "clipId": clip_id,
                                "edge": "start", "delta": head_delta, "ripple": False},
                },
            })
            next_id += 1

        if tail_excess > 0.001:
            p2_reqs.append({
                "jsonrpc": "2.0", "id": next_id, "method": "edit.apply",
                "params": {
                    "path": project_dir,
                    "command": {"op": "trimClip", "clipId": clip_id,
                                "edge": "end", "delta": -tail_excess, "ripple": False},
                },
            })
            next_id += 1

        # Fill framing (landscape → portrait)
        p2_reqs.append({
            "jsonrpc": "2.0", "id": next_id, "method": "edit.apply",
            "params": {
                "path": project_dir,
                "command": {"op": "frameClip", "clipId": clip_id, "framing": "fill"},
            },
        })
        next_id += 1

        # Horizontal offset to align subject
        if transform.get("offsetX") is not None:
            p2_reqs.append({
                "jsonrpc": "2.0", "id": next_id, "method": "edit.apply",
                "params": {
                    "path": project_dir,
                    "command": {
                        "op": "setClipTransform",
                        "clipId": clip_id,
                        "offsetX": transform["offsetX"],
                    },
                },
            })
            next_id += 1

        # Multi-scene keyframe offsets
        if req.keypoints and len(req.keypoints) > 1:
            kf_list = keypoints_to_concat_transforms(
                req.keypoints, req.duration_s,
                req.src_w, req.src_h, req.canvas_w, req.canvas_h
            )
            kf_cmds = [
                {"op": "setClipKey", "clipId": clip_id,
                 "property": "offsetX", "at": kf["at"], "value": kf["offsetX"]}
                for kf in kf_list
            ]
            if kf_cmds:
                p2_reqs.append({
                    "jsonrpc": "2.0", "id": next_id, "method": "edit.apply",
                    "params": {
                        "path": project_dir,
                        "command": {"op": "batch", "commands": kf_cmds},
                    },
                })
                next_id += 1

        # Captions as text clips (skip silently if words missing required fields)
        if req.caption_words:
            caption_cmds = _build_caption_commands(req)
            if caption_cmds:
                p2_reqs.append({
                    "jsonrpc": "2.0", "id": next_id, "method": "edit.apply",
                    "params": {
                        "path": project_dir,
                        "command": {"op": "batch", "commands": caption_cmds},
                    },
                })
                next_id += 1

        p2_reqs.append({
            "jsonrpc": "2.0", "id": next_id, "method": "project.save",
            "params": {"path": project_dir},
        })
        next_id += 1

        export_id = next_id
        p2_reqs.append({
            "jsonrpc": "2.0", "id": export_id, "method": "export.run",
            "params": {
                "path": project_dir,
                "output": req.output_path,
                "width": req.canvas_w,
                "height": req.canvas_h,
                "crf": req.crf,
                "codec": req.codec,
                "rateNum": int(req.fps),
                "rateDen": 1,
            },
        })

        # export.run is the last request — concat-cli waits for export to finish
        r2 = client_export.run_batch(p2_reqs)

        # Verify export success from events
        events = r2.get("_events", [])
        done_event = next(
            (e for e in events if e.get("method") == "export.done"), None
        )
        fail_event = next(
            (e for e in events if e.get("method") == "export.failed"), None
        )

        if fail_event:
            err = fail_event.get("params", {}).get("error", "unknown")
            raise ConcatExportFailed(f"Concat export failed: {err}")

        if not done_event:
            export_resp = r2.get(export_id, {})
            if export_resp.get("error"):
                raise ConcatExportFailed(
                    export_resp["error"].get("message", "export.run error")
                )
            # No done event but no failure either — check file on disk
            logger.warning("No export.done event received; checking output file")

        render_time = time.monotonic() - t0
        out = Path(req.output_path)
        if not out.exists() or out.stat().st_size == 0:
            raise ConcatExportFailed(f"Export completed but output missing: {req.output_path}")

        size = out.stat().st_size
        meta = self._probe(req.output_path)

        logger.info(
            "Concat render done: %s in %.1fs (concat-cli v%s)",
            out.name, render_time, CONCAT_VERSION
        )

        return ConcatRenderResult(
            output_path=req.output_path,
            project_path=project_dir,
            engine_version=CONCAT_VERSION,
            render_time_s=render_time,
            duration_s=meta.get("duration", req.duration_s),
            width=meta.get("width", req.canvas_w),
            height=meta.get("height", req.canvas_h),
            file_size_bytes=size,
        )

    def _probe(self, path: str) -> dict:
        from engine.config import CONFIG
        try:
            r = subprocess.run(
                [CONFIG.ffprobe_path, "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-show_format", path],
                capture_output=True, text=True, timeout=10
            )
            data = _json.loads(r.stdout)
            fmt = data.get("format", {})
            vs = next(
                (s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}
            )
            return {
                "duration": float(fmt.get("duration", 0)),
                "width": int(vs.get("width", 0)),
                "height": int(vs.get("height", 0)),
            }
        except Exception:
            return {}


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_media_duration(import_result: dict, media_id: str) -> float:
    """Extract duration of the imported media item from an EditorView."""
    try:
        bin_items = import_result.get("project", {}).get("bin", [])
        for item in bin_items:
            if item.get("id") == media_id:
                return float(item.get("duration") or 0)
        if bin_items:
            return float(bin_items[-1].get("duration") or 0)
    except Exception:
        pass
    return 0.0


def _get_default_track(create_result: dict) -> str:
    """Return the first video track ID from an EditorView."""
    try:
        tl = create_result.get("project", {}).get("timelines", [{}])[0]
        tracks = tl.get("tracks", [])
        if tracks:
            return tracks[0].get("id") or "T1"
    except Exception:
        pass
    return "T1"


def _build_caption_commands(req: ConcatRenderRequest) -> list[dict]:
    """Build addTextClip commands for word-level captions."""
    cmds = []
    for w in req.caption_words:
        try:
            start = float(w["start"]) - req.start_s
            end = float(w["end"]) - req.start_s
            word = str(w.get("word", "")).strip()
            if not word or start < 0 or end <= start:
                continue
            duration = end - start
            cmds.append({
                "op": "addTextClip",
                "trackId": None,
                "above": True,
                "start": start,
                "duration": duration,
                "style": {
                    "text": word,
                    "size": 0.07,
                    "bold": True,
                    "align": "center",
                },
                "offsetY": 0.7,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return cmds
