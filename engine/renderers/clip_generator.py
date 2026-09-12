"""Clip extraction: cut video windows to individual clip files."""
import subprocess
import os
from pathlib import Path

from engine.config import CONFIG
from engine import database as db


def generate_clips(job_id: str, video_path: str, finalists: list[dict], output_subdir: str = "clips") -> list[str]:
    out_dir = Path(CONFIG.output_dir) / output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    clip_ids = []
    for i, cand in enumerate(finalists):
        clip_path = str(out_dir / f"clip{i+1:02d}.mp4")
        success = _cut_clip(video_path, cand["start_s"], cand["end_s"], clip_path)
        if not success:
            continue

        clip_id = db.create_clip(job_id, cand["id"])
        meta = _probe_clip(clip_path)
        db.update_clip(clip_id,
            output_path=clip_path,
            width=meta.get("width"),
            height=meta.get("height"),
            fps=meta.get("fps"),
            duration_s=meta.get("duration"),
            file_size=meta.get("size"),
        )
        clip_ids.append(clip_id)

    return clip_ids


def _cut_clip(video_path: str, start: float, end: float, out_path: str) -> bool:
    duration = end - start
    cmd = [
        CONFIG.ffmpeg_path, "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    return result.returncode == 0


def _probe_clip(path: str) -> dict:
    import json
    cmd = [
        CONFIG.ffprobe_path, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {}
    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    vs = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fps_str = vs.get("r_frame_rate", "30/1")
    if "/" in str(fps_str):
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    else:
        fps = float(fps_str)
    return {
        "duration": float(fmt.get("duration", 0)),
        "size": int(fmt.get("size", 0)),
        "width": vs.get("width", 0),
        "height": vs.get("height", 0),
        "fps": round(fps, 3),
    }
