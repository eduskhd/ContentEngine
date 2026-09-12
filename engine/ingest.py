"""Ingestion: validate source, extract metadata, verify rights."""
import subprocess
import json
import os
from pathlib import Path

from engine.config import CONFIG
from engine import database as db


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".aac", ".ogg", ".wav", ".flac"}


def ingest(job_id: str, source_path: str) -> str:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    ext = path.suffix.lower()

    # Auto-convert audio-only files to MP4 with black video track
    if ext in AUDIO_EXTENSIONS:
        source_path = _audio_to_mp4(source_path)
        path = Path(source_path)
        ext = path.suffix.lower()

    if ext not in VIDEO_EXTENSIONS:
        raise ValueError(f"Unsupported format: {path.suffix}")

    meta = _probe(source_path)
    duration = float(meta.get("duration", 0))
    fps = _parse_fps(meta)
    width = int(meta.get("width", 0))
    height = int(meta.get("height", 0))
    size = path.stat().st_size

    if duration < 5:
        raise ValueError(f"Video too short: {duration:.1f}s")

    video_id = db.create_video(job_id, source_path, duration, fps, width, height, size)
    db.update_job(job_id, status="INGESTING")
    return video_id


def _probe(path: str) -> dict:
    cmd = [
        CONFIG.ffprobe_path, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    return {
        "duration": fmt.get("duration", video_stream.get("duration", 0)),
        "size": fmt.get("size", 0),
        "fps": video_stream.get("r_frame_rate", "30/1"),
        "width": video_stream.get("width", 0),
        "height": video_stream.get("height", 0),
        "codec": video_stream.get("codec_name", "unknown"),
    }


def _audio_to_mp4(audio_path: str) -> str:
    """Convert audio-only file to MP4 with black 9:16 video track."""
    out_path = str(Path(audio_path).with_suffix(".mp4"))
    cmd = [
        CONFIG.ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30",
        "-i", audio_path,
        "-shortest",
        "-c:v", "libx264", "-crf", "28", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Audio-to-MP4 conversion failed: {result.stderr.decode()[:300]}")
    return out_path


def _parse_fps(meta: dict) -> float:
    fps_str = meta.get("fps", "30/1")
    if isinstance(fps_str, (int, float)):
        return float(fps_str)
    if "/" in str(fps_str):
        num, den = fps_str.split("/")
        return float(num) / float(den) if float(den) else 30.0
    return float(fps_str)
