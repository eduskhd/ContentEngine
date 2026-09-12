from publishers.tiktok import TikTokPublisher
from publishers.instagram import InstagramPublisher
from publishers.youtube import YouTubePublisher
from publishers.base import BasePublisher, PublishResult

_REGISTRY = {
    "tiktok": TikTokPublisher,
    "instagram": InstagramPublisher,
    "youtube": YouTubePublisher,
}


def get_publisher(platform: str) -> BasePublisher:
    cls = _REGISTRY.get(platform.lower())
    if not cls:
        raise ValueError(f"Unknown platform '{platform}'. Available: {list(_REGISTRY)}")
    return cls()


def available_platforms() -> list[str]:
    return list(_REGISTRY)
