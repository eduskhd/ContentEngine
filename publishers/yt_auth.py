"""
YouTube OAuth 2.0 with PKCE for installed/desktop apps.

Desktop app (installed application) flow. Client secret is acceptable in .env
since the app runs locally on a trusted machine. PKCE (code_challenge_method=S256)
added for defense-in-depth against authorization code interception. Redirect URI is
http://localhost:8000/oauth/youtube/callback — register exactly this in Google Cloud Console.

Token storage: ~/.contentengine/yt_tokens.json — outside repo and DB.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import urllib.request

logger = logging.getLogger(__name__)

_TOKEN_DIR = Path.home() / ".contentengine"
_TOKEN_FILE = _TOKEN_DIR / "yt_tokens.json"

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_YT_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

REDIRECT_URI = "http://localhost:8000/oauth/youtube/callback"


def _get_client_id() -> str:
    cid = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    if not cid:
        raise RuntimeError("YOUTUBE_CLIENT_ID not set in environment")
    return cid


def _get_client_secret() -> str:
    cs = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    if not cs:
        raise RuntimeError("YOUTUBE_CLIENT_SECRET not set in environment")
    return cs


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). Challenge = base64url(SHA256(verifier))."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ── Auth URL ──────────────────────────────────────────────────────────────────

def get_auth_url(state: str, code_verifier: str) -> str:
    """Build Google OAuth authorization URL with PKCE."""
    _, code_challenge = generate_pkce()
    # Recompute challenge from the provided verifier
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    params = {
        "client_id": _get_client_id(),
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


# ── Token exchange ────────────────────────────────────────────────────────────

def exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for tokens. Returns token dict."""
    payload = urlencode({
        "client_id": _get_client_id(),
        "client_secret": _get_client_secret(),
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(
        _GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    _enrich_and_save(data)
    return data


def _enrich_and_save(token_data: dict) -> None:
    """Add expires_at ISO string and persist to disk."""
    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc).isoformat()
    token_data["expires_at"] = expires_at
    save_tokens(token_data)


# ── Token storage ─────────────────────────────────────────────────────────────

def save_tokens(token_dict: dict) -> None:
    """Write tokens to disk. Never logged."""
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(json.dumps(token_dict, indent=2), encoding="utf-8")
    # Restrict permissions on Unix (no-op on Windows but harmless)
    try:
        _TOKEN_FILE.chmod(0o600)
    except Exception:
        pass


def load_tokens() -> dict | None:
    """Read tokens from disk. Returns None if file missing or invalid."""
    if not _TOKEN_FILE.exists():
        return None
    try:
        return json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_connected() -> bool:
    """True if we have a refresh_token on disk."""
    tokens = load_tokens()
    return bool(tokens and tokens.get("refresh_token"))


# ── Token refresh ─────────────────────────────────────────────────────────────

def refresh_access_token() -> str:
    """Refresh using the stored refresh_token. Returns new access_token."""
    tokens = load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise RuntimeError("No refresh token stored — re-authenticate via /youtube/connect")
    payload = urlencode({
        "client_id": _get_client_id(),
        "client_secret": _get_client_secret(),
        "refresh_token": tokens["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        _GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    # Preserve existing refresh_token (Google may not return a new one)
    if not data.get("refresh_token"):
        data["refresh_token"] = tokens["refresh_token"]
    _enrich_and_save(data)
    return data["access_token"]


def get_valid_token() -> str | None:
    """Return a valid access_token, auto-refreshing if needed. Returns None if not connected."""
    tokens = load_tokens()
    if not tokens:
        return None
    expires_at_str = tokens.get("expires_at")
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            if (expires_at - now).total_seconds() < 60:
                return refresh_access_token()
        except Exception:
            pass
    access_token = tokens.get("access_token")
    if not access_token:
        return refresh_access_token()
    return access_token


# ── Revoke ────────────────────────────────────────────────────────────────────

def revoke_tokens() -> None:
    """Revoke access token at Google and delete local token file."""
    tokens = load_tokens()
    if tokens:
        token_to_revoke = tokens.get("access_token") or tokens.get("refresh_token")
        if token_to_revoke:
            try:
                req = urllib.request.Request(
                    f"{_GOOGLE_REVOKE_URL}?token={token_to_revoke}",
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass
    try:
        _TOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── Channel info ──────────────────────────────────────────────────────────────

def fetch_channel_info(access_token: str) -> dict:
    """Fetch channel id/title for the authenticated user."""
    url = f"{_YT_CHANNELS_URL}?part=snippet&mine=true"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    items = data.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found for this account")
    ch = items[0]
    snippet = ch.get("snippet", {})
    thumbnails = snippet.get("thumbnails", {})
    thumb_url = (
        thumbnails.get("default", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or ""
    )
    return {
        "channel_id": ch["id"],
        "title": snippet.get("title", ""),
        "thumbnail_url": thumb_url,
    }
