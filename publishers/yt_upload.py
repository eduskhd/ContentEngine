"""
YouTube Data API v3 resumable upload engine.

privacyStatus is ALWAYS forced to 'private' regardless of caller value.
session_url is a sensitive value and must never be exposed to clients.
"""
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_YT_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


# ── Compatibility check ───────────────────────────────────────────────────────

def check_shorts_compatibility(clip_row: dict) -> dict:
    """Check if a clip is Shorts-compatible. Never blocks — only warns."""
    warnings = []
    compatible = True
    duration = clip_row.get("duration_s") or 0
    width = clip_row.get("width") or 0
    height = clip_row.get("height") or 0

    if duration > 60:
        warnings.append(f"Duration {duration:.0f}s exceeds 60s — may not qualify as Short")
        compatible = False

    if width and height:
        ratio = width / height
        if not (0.5 < ratio < 0.6):
            warnings.append(f"Aspect ratio {width}:{height} ({ratio:.2f}) is not 9:16 — may not be promoted as Short")

    return {"compatible": compatible, "warnings": warnings}


# ── File hash ─────────────────────────────────────────────────────────────────

def compute_file_hash(path: str) -> str:
    """Fast hash: MD5 of first 64KB + file size string. Not cryptographic."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(65536)
    h = hashlib.md5(head + str(size).encode()).hexdigest()
    return h


# ── Resumable session creation ────────────────────────────────────────────────

def create_resumable_session(
    access_token: str,
    title: str,
    description: str,
    tags: list[str],
    file_size: int,
    is_for_kids: bool,
) -> str:
    """
    Create a YouTube resumable upload session.
    Returns the upload session URL (keep private — never expose to clients).
    privacyStatus is FORCED to 'private' regardless of any caller value.
    """
    title = (title or "Short")[:100]
    description = (description or "")[:5000]
    safe_tags = [str(t)[:500] for t in (tags or [])]

    body = json.dumps({
        "snippet": {
            "title": title,
            "description": description,
            "tags": safe_tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "private",  # FORCED — do not change
            "selfDeclaredMadeForKids": bool(is_for_kids),
        },
    }).encode()

    url = f"{_YT_UPLOAD_URL}?uploadType=resumable&part=snippet,status"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/*",
            "X-Upload-Content-Length": str(file_size),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        session_url = resp.headers.get("Location")
    if not session_url:
        raise RuntimeError("No Location header in YouTube resumable session response")
    return session_url


# ── Upload chunk ──────────────────────────────────────────────────────────────

def upload_chunk(
    session_url: str,
    file_path: str,
    bytes_offset: int,
    chunk_size: int = CHUNK_SIZE,
) -> dict:
    """
    Upload one chunk to the resumable session.
    Returns {done, bytes_sent, video_id, status_code}.
    """
    file_size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        f.seek(bytes_offset)
        chunk = f.read(chunk_size)

    chunk_end = bytes_offset + len(chunk) - 1
    content_range = f"bytes {bytes_offset}-{chunk_end}/{file_size}"

    req = urllib.request.Request(
        session_url,
        data=chunk,
        headers={
            "Content-Length": str(len(chunk)),
            "Content-Range": content_range,
        },
        method="PUT",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = resp.status
            if status in (200, 201):
                data = json.loads(resp.read())
                return {
                    "done": True,
                    "bytes_sent": file_size,
                    "video_id": data.get("id"),
                    "status_code": status,
                }
    except urllib.error.HTTPError as e:
        if e.code == 308:
            # Resume Incomplete — chunk accepted, more needed
            range_header = e.headers.get("Range", "")
            sent = 0
            if range_header.startswith("bytes="):
                try:
                    sent = int(range_header.split("-")[1]) + 1
                except Exception:
                    sent = bytes_offset + len(chunk)
            return {
                "done": False,
                "bytes_sent": sent,
                "video_id": None,
                "status_code": 308,
            }
        raise

    return {
        "done": False,
        "bytes_sent": bytes_offset + len(chunk),
        "video_id": None,
        "status_code": 0,
    }


# ── Resume session ────────────────────────────────────────────────────────────

def resume_session(session_url: str, file_path: str) -> int:
    """
    Query YouTube for how many bytes have been received.
    Returns the byte offset to resume from.
    """
    file_size = os.path.getsize(file_path)
    req = urllib.request.Request(
        session_url,
        data=b"",
        headers={
            "Content-Length": "0",
            "Content-Range": f"bytes */{file_size}",
        },
        method="PUT",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
        # 200/201 means already complete
        return file_size
    except urllib.error.HTTPError as e:
        if e.code == 308:
            range_header = e.headers.get("Range", "")
            if range_header.startswith("bytes="):
                try:
                    return int(range_header.split("-")[1]) + 1
                except Exception:
                    pass
            return 0
        if e.code == 404:
            return -1  # Session expired, need new session
        raise


# ── Poll video processing status ─────────────────────────────────────────────

def poll_video_status(video_id: str, access_token: str) -> dict:
    """Query YouTube for video processing/privacy status."""
    url = f"{_YT_VIDEOS_URL}?id={video_id}&part=status"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    items = data.get("items", [])
    if not items:
        return {"process_status": "unknown", "privacy_status": "unknown"}
    status = items[0].get("status", {})
    return {
        "process_status": status.get("uploadStatus", "unknown"),
        "privacy_status": status.get("privacyStatus", "unknown"),
    }


# ── Error classification ──────────────────────────────────────────────────────

def classify_error(exc_or_response) -> str:
    """Classify an exception or HTTP error into a stable error code."""
    if isinstance(exc_or_response, urllib.error.HTTPError):
        code = exc_or_response.code
        if code == 403:
            try:
                body = exc_or_response.read().decode(errors="replace")
                if "quotaExceeded" in body or "userRateLimitExceeded" in body:
                    return "QUOTA_EXCEEDED"
                if "forbidden" in body.lower():
                    return "PERMISSION_ERROR"
            except Exception:
                pass
            return "PERMISSION_ERROR"
        if code == 401:
            return "AUTH_REVOKED"
        if code in (400, 422):
            return "INVALID_FILE"
        if code in (500, 502, 503, 504):
            return "TRANSIENT"
        return "UNKNOWN"
    if isinstance(exc_or_response, (ConnectionError, TimeoutError, OSError)):
        return "TRANSIENT"
    msg = str(exc_or_response).lower()
    if "quota" in msg:
        return "QUOTA_EXCEEDED"
    if "unauthorized" in msg or "401" in msg or "revoked" in msg:
        return "AUTH_REVOKED"
    if "permission" in msg or "403" in msg or "forbidden" in msg:
        return "PERMISSION_ERROR"
    if "timeout" in msg or "connection" in msg or "reset" in msg:
        return "TRANSIENT"
    return "UNKNOWN"
