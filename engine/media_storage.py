"""
MediaStorage — local file abstraction layer.

Wraps the existing path conventions used by ContentEngine.
Does NOT move files or change DB records. Read-only discovery only.
Designed to be extended to cloud backends without touching callers.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MediaFile:
    """Represents a single media artifact with its on-disk state."""
    path: str
    exists: bool
    size_bytes: int = 0
    media_type: str = ""   # "video", "audio", "proxy", "thumbnail", "clip", "captioned"

    @classmethod
    def from_path(cls, path: Optional[str], media_type: str = "") -> "MediaFile":
        if not path:
            return cls(path="", exists=False, media_type=media_type)
        p = Path(path)
        if p.is_file():
            return cls(path=path, exists=True, size_bytes=p.stat().st_size, media_type=media_type)
        return cls(path=path, exists=False, media_type=media_type)


@dataclass
class VideoMediaBundle:
    """All media files associated with a single video."""
    video_id: str
    source: MediaFile = field(default_factory=lambda: MediaFile("", False))
    audio: MediaFile = field(default_factory=lambda: MediaFile("", False))
    proxy: MediaFile = field(default_factory=lambda: MediaFile("", False))
    thumbnail: MediaFile = field(default_factory=lambda: MediaFile("", False))

    @property
    def total_bytes(self) -> int:
        return sum(
            f.size_bytes for f in (self.source, self.audio, self.proxy, self.thumbnail)
        )

    @property
    def is_complete(self) -> bool:
        """True if the source video and proxy exist (minimum for re-analysis)."""
        return self.source.exists and self.proxy.exists


@dataclass
class ClipMediaBundle:
    """All media files associated with a single clip."""
    clip_id: str
    output: MediaFile = field(default_factory=lambda: MediaFile("", False))
    captioned: MediaFile = field(default_factory=lambda: MediaFile("", False))

    @property
    def total_bytes(self) -> int:
        return self.output.size_bytes + self.captioned.size_bytes

    @property
    def is_renderable(self) -> bool:
        return self.output.exists


class LocalMediaStorage:
    """
    Local filesystem implementation of media storage.

    All paths are absolute. No files are moved or deleted.
    This class is read-only — it discovers and reports, never mutates.
    """

    def get_video(self, video_row: dict) -> VideoMediaBundle:
        """Build a VideoMediaBundle from a videos DB row."""
        return VideoMediaBundle(
            video_id=video_row.get("id", ""),
            source=MediaFile.from_path(video_row.get("path"), "video"),
            audio=MediaFile.from_path(video_row.get("audio_path"), "audio"),
            proxy=MediaFile.from_path(video_row.get("proxy_path"), "proxy"),
            thumbnail=MediaFile.from_path(video_row.get("thumbnail_path"), "thumbnail"),
        )

    def get_clip(self, clip_row: dict) -> ClipMediaBundle:
        """Build a ClipMediaBundle from a clips DB row."""
        return ClipMediaBundle(
            clip_id=clip_row.get("id", ""),
            output=MediaFile.from_path(clip_row.get("output_path"), "clip"),
            captioned=MediaFile.from_path(clip_row.get("captioned_path"), "captioned"),
        )

    def audit_videos(self, video_rows: list[dict]) -> dict:
        """
        Scan all videos and return accessibility summary.
        Returns dict with counts and lists of problematic video_ids.
        """
        total = len(video_rows)
        missing_source = []
        missing_proxy = []
        complete = []

        for row in video_rows:
            bundle = self.get_video(row)
            if not bundle.source.exists:
                missing_source.append(row["id"])
            if not bundle.proxy.exists:
                missing_proxy.append(row["id"])
            if bundle.is_complete:
                complete.append(row["id"])

        return {
            "total": total,
            "complete": len(complete),
            "missing_source": missing_source,
            "missing_proxy": missing_proxy,
        }

    def audit_clips(self, clip_rows: list[dict]) -> dict:
        """
        Scan all clips and return accessibility summary.
        """
        total = len(clip_rows)
        no_path = []
        missing_file = []
        ok = []

        for row in clip_rows:
            if not row.get("output_path"):
                no_path.append(row["id"])
                continue
            bundle = self.get_clip(row)
            if not bundle.output.exists:
                missing_file.append(row["id"])
            else:
                ok.append(row["id"])

        return {
            "total": total,
            "ok": len(ok),
            "no_path_recorded": len(no_path),
            "path_recorded_but_missing": len(missing_file),
        }

    def storage_summary(self, video_rows: list[dict], clip_rows: list[dict]) -> dict:
        """Total storage breakdown by media type."""
        totals = {"video": 0, "audio": 0, "proxy": 0, "thumbnail": 0, "clip": 0, "captioned": 0}

        for row in video_rows:
            b = self.get_video(row)
            totals["video"] += b.source.size_bytes
            totals["audio"] += b.audio.size_bytes
            totals["proxy"] += b.proxy.size_bytes
            totals["thumbnail"] += b.thumbnail.size_bytes

        for row in clip_rows:
            b = self.get_clip(row)
            totals["clip"] += b.output.size_bytes
            totals["captioned"] += b.captioned.size_bytes

        total_bytes = sum(totals.values())
        return {
            "by_type_bytes": totals,
            "total_bytes": total_bytes,
            "total_gb": round(total_bytes / (1024**3), 2),
        }


# Module-level singleton — callers import this directly
storage = LocalMediaStorage()
