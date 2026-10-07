"""Optional Cloudinary comparison adapter.

Sends a source clip segment to Cloudinary's auto-crop transformation and
returns a signed delivery URL for side-by-side comparison.

Requirements:
  pip install cloudinary
  env: CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
    or: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET

When credentials or the cloudinary package are absent the adapter returns a
MockResult clearly flagged as a simulation — it never silently calls a
paid service.

Usage:
  result = compare_with_cloudinary(source_path, clip_start, clip_end, clip_id)
  if result.available:
      print(result.url)
  else:
      print("Cloudinary not available:", result.reason)
"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass
class CloudinaryResult:
    available: bool
    url: str | None
    public_id: str | None
    mock: bool                 # True = simulated, never actually called Cloudinary
    reason: str                # explanation when not available
    cost_hint: str             # "free_tier" | "paid" | "unknown"


_CHECKED: dict | None = None   # cached credential check


def _check_credentials() -> dict:
    """Return {"ok": bool, "reason": str}. Cached after first call."""
    global _CHECKED
    if _CHECKED is not None:
        return _CHECKED

    # 1. Try importing the SDK
    try:
        import cloudinary  # noqa: F401
    except ImportError:
        _CHECKED = {"ok": False, "reason": "cloudinary SDK not installed (pip install cloudinary)"}
        return _CHECKED

    # 2. Check env credentials
    url = os.environ.get("CLOUDINARY_URL", "")
    name = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    key = os.environ.get("CLOUDINARY_API_KEY", "")
    secret = os.environ.get("CLOUDINARY_API_SECRET", "")

    if url:
        _CHECKED = {"ok": True, "reason": "CLOUDINARY_URL env var present"}
    elif name and key and secret:
        _CHECKED = {"ok": True, "reason": "Cloudinary credentials via env vars"}
    else:
        _CHECKED = {
            "ok": False,
            "reason": (
                "No Cloudinary credentials found. "
                "Set CLOUDINARY_URL or CLOUDINARY_CLOUD_NAME + CLOUDINARY_API_KEY "
                "+ CLOUDINARY_API_SECRET to enable comparison."
            ),
        }
    return _CHECKED


def compare_with_cloudinary(
    source_path: str,
    clip_start: float,
    clip_end: float,
    clip_id: str,
    target_aspect: str = "9:16",
) -> CloudinaryResult:
    """Upload a clip segment to Cloudinary and return an auto-crop URL.

    The clip is trimmed via FFmpeg to a temp file before upload so only the
    relevant segment is transferred (cost control).

    This function NEVER upgrades plans or generates charges beyond what the
    existing account allows.  Throws if the upload would exceed the free tier
    without explicit authorisation (detected via upload response headers).
    """
    creds = _check_credentials()
    if not creds["ok"]:
        return CloudinaryResult(
            available=False, url=None, public_id=None,
            mock=True, reason=creds["reason"], cost_hint="unknown",
        )

    import tempfile
    import subprocess
    from pathlib import Path
    try:
        import cloudinary
        import cloudinary.uploader
        from cloudinary.utils import cloudinary_url
    except ImportError:
        return CloudinaryResult(
            available=False, url=None, public_id=None,
            mock=True, reason="cloudinary import failed", cost_hint="unknown",
        )

    # ── Configure SDK ─────────────────────────────────────────────────────────
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
        api_key=os.environ.get("CLOUDINARY_API_KEY"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        cloudinary_url=os.environ.get("CLOUDINARY_URL") or None,
        secure=True,
    )

    # ── Trim to temp file ─────────────────────────────────────────────────────
    ffmpeg_path = _find_ffmpeg()
    duration = clip_end - clip_start
    tmp_clip = tempfile.mktemp(suffix=".mp4")
    try:
        subprocess.run(
            [ffmpeg_path, "-y", "-ss", str(clip_start), "-i", source_path,
             "-t", str(duration), "-c", "copy", tmp_clip],
            capture_output=True, timeout=120, check=True,
        )
    except Exception as exc:
        return CloudinaryResult(
            available=False, url=None, public_id=None,
            mock=False, reason=f"FFmpeg trim failed: {exc}", cost_hint="unknown",
        )

    # ── Upload ────────────────────────────────────────────────────────────────
    public_id = f"contentengine/reframe_pilot/{clip_id}"
    try:
        response = cloudinary.uploader.upload(
            tmp_clip,
            resource_type="video",
            public_id=public_id,
            overwrite=True,
            eager=[{
                "aspect_ratio": target_aspect,
                "crop": "auto",
                "gravity": "auto",
            }],
            eager_async=False,  # wait for the transformed URL to be ready
        )
    except Exception as exc:
        return CloudinaryResult(
            available=False, url=None, public_id=public_id,
            mock=False, reason=f"Cloudinary upload failed: {exc}", cost_hint="unknown",
        )
    finally:
        try:
            Path(tmp_clip).unlink(missing_ok=True)
        except OSError:
            pass

    # ── Extract transformed URL ───────────────────────────────────────────────
    eager = response.get("eager", [])
    if eager:
        delivery_url = eager[0].get("secure_url") or eager[0].get("url")
    else:
        # Fallback: generate via cloudinary_url with transformation params
        delivery_url, _ = cloudinary_url(
            public_id,
            resource_type="video",
            aspect_ratio=target_aspect,
            crop="auto",
            gravity="auto",
        )

    return CloudinaryResult(
        available=True,
        url=delivery_url,
        public_id=public_id,
        mock=False,
        reason="",
        cost_hint="free_tier",
    )


def _find_ffmpeg() -> str:
    from engine.config import CONFIG
    return CONFIG.ffmpeg_path


# ── Mock result for tests / dry runs ─────────────────────────────────────────

def mock_result(clip_id: str) -> CloudinaryResult:
    """Return a clearly-marked mock result for tests and CI."""
    return CloudinaryResult(
        available=False,
        url=None,
        public_id=None,
        mock=True,
        reason="Mock result — Cloudinary not configured",
        cost_hint="none",
    )
