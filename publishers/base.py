"""Base publisher interface. All platform adapters extend this."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PublishResult:
    platform: str
    success: bool
    post_id: str = None
    url: str = None
    error: str = None


class BasePublisher(ABC):
    platform: str = "unknown"

    @abstractmethod
    def is_authorized(self) -> bool:
        """True only if OAuth tokens are present and non-empty."""
        ...

    @abstractmethod
    def publish(self, clip, caption: str, hashtags: list[str]) -> PublishResult:
        """Publish a clip. Called only when rights_verified=True and gate=PUBLISH."""
        ...

    @abstractmethod
    def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        """Return (auth_url, state) for the OAuth flow."""
        ...

    @abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange OAuth code for tokens."""
        ...
