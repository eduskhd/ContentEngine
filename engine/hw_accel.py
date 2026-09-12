"""Hardware acceleration detection for FFmpeg encoding."""
import subprocess
from functools import lru_cache

from engine.config import CONFIG

_FFMPEG = CONFIG.ffmpeg_path


def _probe_encoder(encoder: str, extra_flags: list[str] = None) -> bool:
    """Return True if FFmpeg can encode with this encoder."""
    cmd = [
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
        "-c:v", encoder,
    ] + (extra_flags or []) + [
        "-frames:v", "1",
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def detect_encoder() -> tuple[str, list[str], int]:
    """
    Detect best available video encoder.

    Returns (encoder_name, extra_opts, max_parallel_renders).

    Priority: NVENC > QSV > CPU.
    max_parallel_renders: how many clip renders to run simultaneously.
    """
    # NVIDIA NVENC
    if _probe_encoder("h264_nvenc", ["-preset", "p4"]):
        return ("h264_nvenc", ["-preset", "p4", "-cq", "20"], 4)

    # Intel Quick Sync Video
    if _probe_encoder("h264_qsv"):
        return ("h264_qsv", ["-global_quality", "23", "-look_ahead", "0"], 3)

    # CPU libx264 — veryfast for a good speed/quality balance
    return ("libx264", ["-preset", "veryfast", "-crf", "20"], 2)


def encoder_summary() -> str:
    enc, opts, par = detect_encoder()
    return f"encoder={enc} opts={opts} parallel_renders={par}"
