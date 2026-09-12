"""yt-dlp based video downloader.

Uses yt_dlp Python library (NOT subprocess) to avoid Windows Application Control
Policy restrictions that block .exe files while allowing Python imports.

Public API:
    is_url(source)          — True if source is an http/https URL
    validate_url(url)       — Raises ValueError for SSRF-unsafe URLs
    get_video_info(url)     — Fetch metadata without downloading (fast, for UI preview)
    download_url(url)       — Download video and return metadata dict
"""
import re, ipaddress, logging
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from engine.config import CONFIG

logger = logging.getLogger("downloader")

_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
_AUDIO_EXTS = {".m4a", ".mp3", ".ogg", ".opus", ".wav", ".aac"}

# SSRF: hostnames that must never be fetched
_BLOCKED_HOSTS = frozenset({
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
    "metadata.google.internal",
    "169.254.169.254",
    "fd00::ec2", "fd00::fe",
})


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def validate_url(url: str) -> None:
    """Raise ValueError for URLs that target private/internal infrastructure (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme not allowed: {parsed.scheme!r} — only http/https")

    hostname = (parsed.hostname or "").lower().strip("[]")
    if not hostname:
        raise ValueError("URL has no hostname")

    if hostname in _BLOCKED_HOSTS:
        raise ValueError(f"URL hostname not allowed: {hostname!r}")

    try:
        addr = ipaddress.ip_address(hostname)
        if (addr.is_private or addr.is_loopback or
                addr.is_link_local or addr.is_reserved or addr.is_unspecified):
            raise ValueError(f"URL points to a private or reserved address: {hostname!r}")
    except ValueError as exc:
        if "not allowed" in str(exc) or "private" in str(exc) or "reserved" in str(exc):
            raise
        # hostname is a domain name — allow it


def get_video_info(url: str) -> dict:
    """Fetch video metadata without downloading. Used by the UI preview endpoint.

    Returns:
        title, channel, channel_id, duration_s, thumbnail, platform, video_id, view_count
    Raises:
        ValueError  — SSRF-unsafe URL
        RuntimeError — platform error (unavailable, private, etc.)
    """
    validate_url(url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(_friendly_error(str(exc)))

    channel = (
        info.get("uploader")
        or info.get("channel")
        or info.get("creator")
        or "Unknown"
    )
    return {
        "title":      info.get("title") or "Untitled",
        "channel":    channel,
        "channel_id": info.get("channel_id") or info.get("uploader_id") or "",
        "duration_s": int(info.get("duration") or 0),
        "thumbnail":  info.get("thumbnail") or "",
        "platform":   info.get("extractor_key", "unknown").lower(),
        "video_id":   info.get("id", ""),
        "view_count": info.get("view_count") or 0,
        "upload_date": info.get("upload_date") or "",
    }


def download_url(url: str) -> dict:
    """Download a video from any URL supported by yt-dlp.

    Returns a dict with:
        path         str   — absolute path to downloaded MP4
        creator      str   — uploader/channel name (display)
        creator_slug str   — filesystem-safe creator name
        title        str   — video title
        video_id     str   — platform video ID
        video_slug   str   — filesystem-safe short ID
        platform     str   — youtube / tiktok / instagram / ...
        duration     float — seconds
        url          str   — original URL
    """
    validate_url(url)

    out_dir = Path(CONFIG.output_dir) / "downloads"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Fetch metadata without downloading ────────────────────────────────
    logger.info("Fetching metadata: %s", url)
    meta_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(meta_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(_friendly_error(str(exc)))

    video_id     = info.get("id", "unknown")
    title        = info.get("title", "untitled")
    creator      = (info.get("uploader") or info.get("channel")
                    or info.get("creator") or "unknown")
    platform     = info.get("extractor_key", "unknown").lower()
    duration     = float(info.get("duration") or 0)
    creator_slug = _slugify(creator)
    video_slug   = _slugify(video_id)

    out_path = out_dir / f"{creator_slug}_{video_slug}.mp4"

    # ── 2. Skip if already on disk ───────────────────────────────────────────
    if out_path.exists() and out_path.stat().st_size > 10_000:
        if _has_audio_stream(out_path):
            logger.info("Cache hit — skipping download: %s", out_path.name)
            return _build_meta(out_path, creator, creator_slug, title,
                               video_id, video_slug, platform, duration, url)
        out_path = _ensure_has_audio(out_dir, creator_slug, video_slug, out_path)
        if out_path.exists():
            return _build_meta(out_path, creator, creator_slug, title,
                               video_id, video_slug, platform, duration, url)

    # ── 3. Download ──────────────────────────────────────────────────────────
    logger.info("Downloading: %s → %s", url, out_path.name)
    ffmpeg_dir = str(Path(CONFIG.ffmpeg_path).parent)

    dl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        # Best quality ≤1080p; fall back to single best stream
        "format": "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        # %(ext)s is replaced by yt-dlp; with merge_output_format=mp4 → .mp4
        "outtmpl": str(out_dir / f"{creator_slug}_{video_slug}.%(ext)s"),
        "ffmpeg_location": ffmpeg_dir,
    }
    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(_friendly_error(str(exc)))

    # ── 4. Locate the output file ────────────────────────────────────────────
    if not out_path.exists():
        out_path = _resolve_output(out_dir, creator_slug, video_slug, out_path)

    # ── 5. Ensure audio stream present ──────────────────────────────────────
    out_path = _ensure_has_audio(out_dir, creator_slug, video_slug, out_path)

    logger.info("Download complete: %s (%.1f MB)", out_path.name,
                out_path.stat().st_size / 1_048_576)
    return _build_meta(out_path, creator, creator_slug, title,
                       video_id, video_slug, platform, duration, url)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _resolve_output(out_dir: Path, creator_slug: str, video_slug: str,
                    target: Path) -> Path:
    """Find the actual downloaded file when yt-dlp named it differently."""
    all_candidates = list(out_dir.glob(f"{creator_slug}_{video_slug}*"))
    video_candidates = [c for c in all_candidates if c.suffix.lower() in _VIDEO_EXTS]
    audio_only       = [c for c in all_candidates if c.suffix.lower() in _AUDIO_EXTS]

    if video_candidates:
        return max(video_candidates, key=lambda p: p.stat().st_size)
    if audio_only:
        src = max(audio_only, key=lambda p: p.stat().st_size)
        _convert_audio_to_mp4(src, target)
        return target
    raise RuntimeError("Download succeeded but output file not found in: " + str(out_dir))


def _has_audio_stream(path: Path) -> bool:
    """Return True if ffprobe finds at least one audio stream."""
    import subprocess
    cmd = [
        CONFIG.ffprobe_path, "-v", "quiet",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0 and "audio" in result.stdout


def _ensure_has_audio(out_dir: Path, creator_slug: str, video_slug: str,
                      video_path: Path) -> Path:
    """If video_path has no audio, find companion audio file and merge."""
    if _has_audio_stream(video_path):
        return video_path

    all_candidates = list(out_dir.glob(f"{creator_slug}_{video_slug}*"))
    audio_candidates = [
        c for c in all_candidates
        if c.suffix.lower() in _AUDIO_EXTS and c != video_path
    ]
    if not audio_candidates:
        return video_path  # silent content — return as-is

    audio_src = max(audio_candidates, key=lambda p: p.stat().st_size)
    merged = out_dir / f"{creator_slug}_{video_slug}.mp4"
    _merge_video_audio(video_path, audio_src, merged)
    return merged


def _merge_video_audio(video: Path, audio: Path, out: Path):
    """Merge a video-only file with an audio-only file into a single MP4."""
    import subprocess
    cmd = [
        CONFIG.ffmpeg_path, "-y",
        "-i", str(video),
        "-i", str(audio),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"Video+audio merge failed: {result.stderr.decode()[-400:]}"
        )


def _convert_audio_to_mp4(audio_path: Path, out_path: Path):
    """Wrap an audio-only file in an MP4 container with a black video track."""
    import subprocess
    cmd = [
        CONFIG.ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30",
        "-i", str(audio_path),
        "-shortest",
        "-c:v", "libx264", "-crf", "28", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"Audio→MP4 conversion failed: {result.stderr.decode()[:300]}"
        )


def _build_meta(path, creator, creator_slug, title, video_id, video_slug,
                platform, duration, url):
    return {
        "path":         str(path),
        "creator":      creator,
        "creator_slug": creator_slug,
        "title":        title,
        "video_id":     video_id,
        "video_slug":   video_slug,
        "platform":     platform,
        "duration":     duration,
        "url":          url,
    }


def _friendly_error(raw: str) -> str:
    """Convert yt-dlp error messages to user-friendly strings."""
    r = raw.lower()
    if "sign in" in r or "login" in r or "age" in r:
        return "This video requires account login (age-restricted or member-only content)"
    if "private" in r:
        return "This video is private"
    if "members" in r:
        return "This is a members-only video"
    if "premiere" in r or "premiering" in r:
        return "This video has not premiered yet"
    if "copyright" in r:
        return "This video has been removed due to a copyright claim"
    if "unavailable" in r or "not available" in r:
        return "This video is unavailable (removed, region-restricted, or deleted)"
    if "live" in r and ("not" in r or "end" in r):
        return "This live stream is not currently available"
    if "does not exist" in r or "no video" in r:
        return "No video found at this URL"
    # Return sanitised version — strip potential internal paths
    msg = re.sub(r"[A-Z]:\\[^\s]+", "[path]", raw)
    msg = re.sub(r"/[^\s]+", "[path]", msg)
    return f"Could not read video: {msg[:300]}"


def _slugify(text: str) -> str:
    text = str(text).lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text).strip("_")
    return text[:40] or "unknown"
