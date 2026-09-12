"""Analysis proxy generator.

Creates a low-resolution version of the master video used exclusively for
visual analysis. The proxy is generated once and cached via videos.proxy_path.

Proxy spec:
  - Resolution: 360p (max height 360, width proportional)
  - Frame rate: 2 fps (sufficient for motion + face detection)
  - Encoder: libx264 ultrafast (fast generation, quality irrelevant)
  - Audio: stripped (not needed for visual analysis)

The master video is never touched for analysis; the proxy is disposable.
"""
import subprocess
from pathlib import Path

from engine.config import CONFIG
from engine import database as db


def generate_proxy(video_id: str, video_path: str) -> str | None:
    """
    Generate analysis proxy for video_path.

    Returns proxy path on success, None on failure (caller falls back to master).
    Skips generation if proxy already exists for this video.
    """
    # Check if proxy already stored in DB (same video_id retry)
    with db.db() as conn:
        row = conn.execute(
            "SELECT proxy_path FROM videos WHERE id=?", (video_id,)
        ).fetchone()
    existing = row["proxy_path"] if row else None
    if existing and Path(existing).exists():
        return existing

    # Check if a previous job processed the same source video
    existing_from_path = db.get_proxy_by_path(video_path)
    if existing_from_path and Path(existing_from_path).exists():
        db.save_proxy_path(video_id, existing_from_path)
        return existing_from_path

    out_dir = Path(CONFIG.output_dir) / "proxies"
    out_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = str(out_dir / f"{video_id}_proxy.mp4")

    cmd = [
        CONFIG.ffmpeg_path, "-y",
        "-i", video_path,
        "-vf", "scale=-2:360",    # 360p, width divisible by 2
        "-r", "2",                 # 2 fps — enough for motion + face
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
        "-an",                     # no audio track
        "-movflags", "+faststart",
        proxy_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)

    if result.returncode == 0:
        db.save_proxy_path(video_id, proxy_path)
        return proxy_path

    return None
