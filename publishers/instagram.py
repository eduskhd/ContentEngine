"""Instagram Graph API — Reels Publishing.
Docs: https://developers.facebook.com/docs/instagram-api/guides/reels-publishing

Required env vars:
    INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET
    INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID
"""
import os, secrets
import requests
from publishers.base import BasePublisher, PublishResult

GRAPH = "https://graph.facebook.com/v21.0"


class InstagramPublisher(BasePublisher):
    platform = "instagram"

    def __init__(self):
        self.app_id = os.environ.get("INSTAGRAM_APP_ID")
        self.app_secret = os.environ.get("INSTAGRAM_APP_SECRET")
        self.access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
        self.user_id = os.environ.get("INSTAGRAM_USER_ID")

    def is_authorized(self) -> bool:
        return bool(self.access_token and self.user_id)

    def get_auth_url(self, redirect_uri: str = "http://localhost:8000/oauth/instagram/callback") -> tuple[str, str]:
        state = secrets.token_urlsafe(16)
        url = (
            f"https://www.facebook.com/dialog/oauth?"
            f"client_id={self.app_id or ''}&redirect_uri={redirect_uri}"
            f"&scope=instagram_basic,instagram_content_publish&state={state}"
        )
        return url, state

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        resp = requests.get(f"{GRAPH}/oauth/access_token", params={
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        })
        resp.raise_for_status()
        return resp.json()

    def publish(self, clip, caption: str = "", hashtags: list = None, video_url: str = None) -> PublishResult:
        """video_url must be a publicly accessible URL to the MP4."""
        if not self.is_authorized():
            return PublishResult(platform="instagram", success=False, error="Not authorized")
        if not video_url:
            return PublishResult(platform="instagram", success=False,
                                 error="video_url is required (publicly accessible MP4 URL)")

        hashtags = hashtags or []
        caption_text = (caption + "\n\n" + " ".join(f"#{h}" for h in hashtags)).strip()[:2200]

        try:
            cr = requests.post(
                f"{GRAPH}/{self.user_id}/media",
                params={"access_token": self.access_token},
                json={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption_text,
                    "share_to_feed": True,
                },
            )
            cr.raise_for_status()
            container_id = cr.json().get("id")

            pr = requests.post(
                f"{GRAPH}/{self.user_id}/media_publish",
                params={"access_token": self.access_token},
                json={"creation_id": container_id},
            )
            pr.raise_for_status()
            media_id = pr.json().get("id")

            return PublishResult(platform="instagram", success=True, post_id=media_id,
                                 url=f"https://www.instagram.com/p/{media_id}/")
        except Exception as e:
            return PublishResult(platform="instagram", success=False, error=str(e))
