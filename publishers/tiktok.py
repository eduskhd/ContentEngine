"""TikTok Content Publishing API v2.
Docs: https://developers.tiktok.com/doc/content-posting-api-get-started

Required env vars (set after OAuth exchange):
    TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET
    TIKTOK_ACCESS_TOKEN, TIKTOK_OPEN_ID
"""
import os, secrets
from pathlib import Path
import requests
from publishers.base import BasePublisher, PublishResult


class TikTokPublisher(BasePublisher):
    platform = "tiktok"
    AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    UPLOAD_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"

    def __init__(self):
        self.client_key = os.environ.get("TIKTOK_CLIENT_KEY")
        self.client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
        self.access_token = os.environ.get("TIKTOK_ACCESS_TOKEN")
        self.open_id = os.environ.get("TIKTOK_OPEN_ID")

    def is_authorized(self) -> bool:
        return bool(self.client_key and self.access_token and self.open_id)

    def get_auth_url(self, redirect_uri: str = "http://localhost:8000/oauth/tiktok/callback") -> tuple[str, str]:
        state = secrets.token_urlsafe(16)
        params = {
            "client_key": self.client_key or "",
            "response_type": "code",
            "scope": "user.info.basic,video.publish",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.AUTH_URL}?{query}", state

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        resp = requests.post(self.TOKEN_URL, data={
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        })
        resp.raise_for_status()
        return resp.json()

    def publish(self, clip, caption: str = "", hashtags: list = None) -> PublishResult:
        if not self.is_authorized():
            return PublishResult(platform="tiktok", success=False, error="Not authorized — run OAuth flow")

        hashtags = hashtags or []
        full_caption = (caption + " " + " ".join(f"#{h}" for h in hashtags)).strip()[:2200]

        video_path = Path(clip.output_path if hasattr(clip, "output_path") else clip["captioned_path"] or clip["output_path"])
        file_size = video_path.stat().st_size

        try:
            init_resp = requests.post(
                self.UPLOAD_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={
                    "post_info": {
                        "title": full_caption,
                        "privacy_level": "SELF_ONLY",
                        "disable_duet": False,
                        "disable_comment": False,
                        "disable_stitch": False,
                        "video_cover_timestamp_ms": 1000,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": file_size,
                        "chunk_size": file_size,
                        "total_chunk_count": 1,
                    },
                },
            )
            init_resp.raise_for_status()
            data = init_resp.json().get("data", {})
            upload_url = data.get("upload_url")
            publish_id = data.get("publish_id")

            if not upload_url:
                return PublishResult(platform="tiktok", success=False, error=f"Init failed: {init_resp.text}")

            with open(video_path, "rb") as f:
                up = requests.put(
                    upload_url, data=f,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
                        "Content-Length": str(file_size),
                    },
                )
            if up.status_code not in (200, 201, 206):
                return PublishResult(platform="tiktok", success=False, error=f"Upload failed: {up.status_code}")

            return PublishResult(platform="tiktok", success=True, post_id=publish_id)
        except Exception as e:
            return PublishResult(platform="tiktok", success=False, error=str(e))
