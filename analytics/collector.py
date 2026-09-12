"""Analytics collector — pulls real engagement metrics from published posts."""
import os, json, sqlite3
from datetime import datetime
from pathlib import Path

from engine.config import CONFIG


class AnalyticsCollector:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or CONFIG.db_path
        self._init_tables()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_tables(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS post_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clip_id TEXT,
                    platform TEXT,
                    post_id TEXT,
                    collected_at TEXT,
                    views INTEGER DEFAULT 0,
                    likes INTEGER DEFAULT 0,
                    comments INTEGER DEFAULT 0,
                    shares INTEGER DEFAULT 0,
                    saves INTEGER DEFAULT 0,
                    reach INTEGER DEFAULT 0,
                    impressions INTEGER DEFAULT 0,
                    engagement_rate REAL DEFAULT 0.0,
                    completion_rate REAL DEFAULT 0.0,
                    hours_since_publish REAL DEFAULT 0.0,
                    raw_json TEXT
                );
                CREATE TABLE IF NOT EXISTS performance_benchmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT,
                    content_type TEXT,
                    percentile_25 REAL,
                    percentile_50 REAL,
                    percentile_75 REAL,
                    percentile_90 REAL,
                    updated_at TEXT
                );
            """)

    # ── PUBLIC API ─────────────────────────────────────────────────────────────

    def collect_all(self):
        """Collect metrics for all published posts not yet updated in the last hour."""
        with self._conn() as conn:
            posts = conn.execute("""
                SELECT pl.clip_id, pl.platform, pl.post_id, pl.published_at
                FROM publish_log pl
                WHERE pl.post_id IS NOT NULL
                  AND (
                    NOT EXISTS (SELECT 1 FROM post_metrics pm WHERE pm.clip_id = pl.clip_id AND pm.platform = pl.platform)
                    OR EXISTS (
                        SELECT 1 FROM post_metrics pm2
                        WHERE pm2.clip_id = pl.clip_id AND pm2.platform = pl.platform
                          AND (strftime('%s','now') - strftime('%s', pm2.collected_at)) > 3600
                    )
                  )
            """).fetchall()

        tiktok_token = os.environ.get("TIKTOK_ACCESS_TOKEN")
        ig_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")

        for post in posts:
            if post["platform"] == "tiktok" and tiktok_token:
                self._collect_tiktok(post["clip_id"], post["post_id"], post["published_at"], tiktok_token)
            elif post["platform"] == "instagram" and ig_token:
                self._collect_instagram(post["clip_id"], post["post_id"], post["published_at"], ig_token)

    def summary(self) -> list[dict]:
        """Per-platform performance summary."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    platform,
                    COUNT(DISTINCT post_id)   AS posts,
                    COALESCE(AVG(views), 0)   AS avg_views,
                    COALESCE(MAX(views), 0)   AS max_views,
                    COALESCE(AVG(likes), 0)   AS avg_likes,
                    COALESCE(AVG(engagement_rate), 0) AS avg_engagement
                FROM post_metrics
                GROUP BY platform
            """).fetchall()
        return [dict(r) for r in rows]

    # ── PLATFORM COLLECTORS ────────────────────────────────────────────────────

    def _collect_tiktok(self, clip_id: str, post_id: str, published_at: str, access_token: str):
        try:
            import requests
            resp = requests.post(
                "https://open.tiktokapis.com/v2/video/query/",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "filters": {"video_ids": [post_id]},
                    "fields": ["id", "view_count", "like_count", "comment_count", "share_count"],
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get("videos", [{}])[0]
                self._save_metrics(clip_id, "tiktok", post_id, published_at, {
                    "views":    data.get("view_count", 0),
                    "likes":    data.get("like_count", 0),
                    "comments": data.get("comment_count", 0),
                    "shares":   data.get("share_count", 0),
                }, raw=data)
        except Exception as exc:
            print(f"[analytics] TikTok collection failed for {post_id}: {exc}")

    def _collect_instagram(self, clip_id: str, post_id: str, published_at: str, access_token: str):
        try:
            import requests
            resp = requests.get(
                f"https://graph.facebook.com/v21.0/{post_id}/insights",
                params={
                    "metric": "impressions,reach,saved,video_views,likes,comments,shares",
                    "access_token": access_token,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                raw = {m["name"]: m.get("values", [{}])[0].get("value", 0)
                       for m in resp.json().get("data", [])}
                self._save_metrics(clip_id, "instagram", post_id, published_at, {
                    "views":       raw.get("video_views", 0),
                    "likes":       raw.get("likes", 0),
                    "comments":    raw.get("comments", 0),
                    "shares":      raw.get("shares", 0),
                    "saves":       raw.get("saved", 0),
                    "reach":       raw.get("reach", 0),
                    "impressions": raw.get("impressions", 0),
                }, raw=raw)
        except Exception as exc:
            print(f"[analytics] Instagram collection failed for {post_id}: {exc}")

    def _save_metrics(self, clip_id: str, platform: str, post_id: str,
                      published_at: str, metrics: dict, raw: dict = None):
        try:
            pub_time = datetime.fromisoformat(published_at)
            hours_since = (datetime.utcnow() - pub_time).total_seconds() / 3600
        except Exception:
            hours_since = 0.0

        views = metrics.get("views", 0)
        engagement = 0.0
        if views > 0:
            engagement = (metrics.get("likes", 0) + metrics.get("comments", 0) + metrics.get("shares", 0)) / views

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO post_metrics
                (clip_id, platform, post_id, collected_at, views, likes, comments, shares,
                 saves, reach, impressions, engagement_rate, hours_since_publish, raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                clip_id, platform, post_id,
                datetime.utcnow().isoformat(),
                views,
                metrics.get("likes", 0),
                metrics.get("comments", 0),
                metrics.get("shares", 0),
                metrics.get("saves", 0),
                metrics.get("reach", 0),
                metrics.get("impressions", 0),
                engagement,
                hours_since,
                json.dumps(raw or {}),
            ])
