"""YouTube Data API v3 — Shorts upload (resumable).
Docs: https://developers.google.com/youtube/v3/docs/videos/insert

Required env vars:
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET
    YOUTUBE_ACCESS_TOKEN, YOUTUBE_REFRESH_TOKEN
"""
import os, json, secrets
from pathlib import Path
import requests
from publishers.base import BasePublisher, PublishResult

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"


class YouTubePublisher(BasePublisher):
    platform = "youtube"

    def __init__(self):
        self.client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        self.client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        self.access_token = os.environ.get("YOUTUBE_ACCESS_TOKEN")
        self.refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    def is_authorized(self) -> bool:
        return bool(self.client_id and (self.access_token or self.refresh_token))

    def get_auth_url(self, redirect_uri: str = "http://localhost:8000/oauth/youtube/callback") -> tuple[str, str]:
        state = secrets.token_urlsafe(16)
        url = (
            f"{AUTH_URL}?client_id={self.client_id or ''}&redirect_uri={redirect_uri}"
            f"&response_type=code&scope=https://www.googleapis.com/auth/youtube.upload"
            f"&access_type=offline&state={state}"
        )
        return url, state

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        resp = requests.post(TOKEN_URL, data={
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        return resp.json()

    def _refresh(self):
        resp = requests.post(TOKEN_URL, data={
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        self.access_token = resp.json().get("access_token")

    def publish(self, clip, caption: str = "", hashtags: list = None) -> PublishResult:
        if not self.is_authorized():
            return PublishResult(platform="youtube", success=False, error="Not authorized")

        if self.refresh_token and not self.access_token:
            self._refresh()

        hashtags = hashtags or []
        description = (caption + "\n\n" + " ".join(f"#{h}" for h in hashtags)).strip()

        video_path = Path(clip.output_path if hasattr(clip, "output_path") else clip["captioned_path"] or clip["output_path"])
        file_size = video_path.stat().st_size

        metadata = {
            "snippet": {
                "title": ((caption[:97] + "...") if len(caption) > 100 else caption or "Short") + " #Shorts",
                "description": description[:5000],
                "tags": hashtags,
                "categoryId": "22",
            },
            "status": {"privacyStatus": "private"},
        }

        try:
            init_resp = requests.post(
                UPLOAD_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(file_size),
                },
                data=json.dumps(metadata),
            )
            if init_resp.status_code != 200:
                return PublishResult(platform="youtube", success=False, error=f"Init failed: {init_resp.text}")

            upload_url = init_resp.headers.get("Location")
            with open(video_path, "rb") as f:
                up = requests.put(
                    upload_url,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(file_size)},
                    data=f,
                )
            if up.status_code not in (200, 201):
                return PublishResult(platform="youtube", success=False, error=f"Upload failed: {up.status_code}")

            video_id = up.json().get("id")
            return PublishResult(platform="youtube", success=True, post_id=video_id,
                                 url=f"https://youtube.com/shorts/{video_id}")
        except Exception as e:
            return PublishResult(platform="youtube", success=False, error=str(e))
