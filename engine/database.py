import sqlite3
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

from engine.config import CONFIG


def get_connection():
    Path(CONFIG.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CONFIG.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db(path: str = None):
    """Return a raw connection for ad-hoc queries. Caller must commit/close."""
    from pathlib import Path as _Path
    target = path or CONFIG.db_path
    _Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'QUEUED',
            mode TEXT NOT NULL DEFAULT 'REVIEW',
            target_clips INTEGER DEFAULT 5,
            target_platforms TEXT DEFAULT '[]',
            creator TEXT,
            content_type TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT,
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            path TEXT NOT NULL,
            duration_s REAL,
            fps REAL,
            width INTEGER,
            height INTEGER,
            size_bytes INTEGER,
            rights_verified INTEGER DEFAULT 0,
            transcript TEXT,
            audio_path TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            score REAL DEFAULT 0.0,
            score_breakdown TEXT DEFAULT '{}',
            virality_score REAL DEFAULT 0.0,
            hook_score REAL DEFAULT 0.0,
            visual_score REAL DEFAULT 0.0,
            audio_score REAL DEFAULT 0.0,
            platform_scores TEXT DEFAULT '{}',
            status TEXT DEFAULT 'DETECTED',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id),
            FOREIGN KEY (video_id) REFERENCES videos(id)
        );

        CREATE TABLE IF NOT EXISTS clips (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            output_path TEXT,
            captioned_path TEXT,
            width INTEGER,
            height INTEGER,
            fps REAL,
            duration_s REAL,
            file_size INTEGER,
            technical_qa TEXT DEFAULT 'PENDING',
            visual_qa TEXT DEFAULT 'PENDING',
            qa_notes TEXT DEFAULT '{}',
            platform_fit_scores TEXT DEFAULT '{}',
            prepublish_decision TEXT DEFAULT 'PENDING',
            prepublish_score REAL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE TABLE IF NOT EXISTS skill_runs (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            input_summary TEXT,
            output TEXT,
            score REAL,
            duration_ms INTEGER,
            status TEXT DEFAULT 'OK',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS prepublish_decisions (
            id TEXT PRIMARY KEY,
            clip_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            score REAL,
            technical_qa TEXT,
            visual_qa TEXT,
            rights_verified INTEGER,
            platform_fit_scores TEXT,
            blocking_reasons TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (clip_id) REFERENCES clips(id),
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS publish_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            post_id TEXT,
            url TEXT,
            published_at TEXT NOT NULL,
            FOREIGN KEY (clip_id) REFERENCES clips(id)
        );

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

        CREATE TABLE IF NOT EXISTS job_queue (
            id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'queued',
            payload TEXT,
            priority INTEGER DEFAULT 0,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            worker_id TEXT,
            error TEXT,
            result TEXT
        );

        CREATE TABLE IF NOT EXISTS weight_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            updated_at TEXT,
            hook_weight REAL,
            viral_weight REAL,
            semantic_weight REAL,
            visual_weight REAL,
            audio_weight REAL,
            platform_fit_weight REAL,
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS autopsy_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at TEXT,
            sample_size INTEGER,
            correlation_hook REAL,
            correlation_viral REAL,
            correlation_visual REAL,
            correlation_audio REAL,
            best_hook_type TEXT,
            optimal_duration_min REAL,
            optimal_duration_max REAL,
            recommendations TEXT
        );
        CREATE TABLE IF NOT EXISTS clip_series (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            series_score REAL DEFAULT 0.0,
            total_parts INTEGER DEFAULT 0,
            series_reasons TEXT DEFAULT '[]',
            original_start REAL,
            original_end REAL,
            title TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS creators (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT,
            handle TEXT,
            avatar_color TEXT DEFAULT '#3b82f6',
            platform TEXT,
            channel_url TEXT,
            external_channel_id TEXT,
            is_favorite INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS publications (
            id TEXT PRIMARY KEY,
            clip_id TEXT NOT NULL,
            creator_id TEXT,
            video_id TEXT,
            series_id TEXT,
            series_part INTEGER DEFAULT 0,
            platform TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            title TEXT,
            caption TEXT,
            hashtags TEXT DEFAULT '[]',
            platform_overrides TEXT DEFAULT '{}',
            scheduled_at TEXT,
            published_at TEXT,
            external_post_id TEXT,
            external_url TEXT,
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            next_retry_at TEXT,
            publication_order INTEGER DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (clip_id) REFERENCES clips(id)
        );
        CREATE TABLE IF NOT EXISTS social_accounts (
            id TEXT PRIMARY KEY,
            creator_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            account_name TEXT,
            external_account_id TEXT,
            connection_status TEXT DEFAULT 'disconnected',
            connected_at TEXT,
            token_reference TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        );
        CREATE TABLE IF NOT EXISTS publication_metrics (
            id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            saves INTEGER DEFAULT 0,
            avg_watch_time_s REAL DEFAULT 0.0,
            completion_rate REAL DEFAULT 0.0,
            followers_generated INTEGER DEFAULT 0,
            collected_at TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            FOREIGN KEY (publication_id) REFERENCES publications(id)
        );
        CREATE TABLE IF NOT EXISTS publication_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pipeline_timings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            start_ts REAL,
            end_ts REAL,
            duration_s REAL,
            status TEXT DEFAULT 'ok',
            meta TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS collections (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            color TEXT DEFAULT '#3b82f6',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS collection_items (
            id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            FOREIGN KEY (collection_id) REFERENCES collections(id),
            UNIQUE(collection_id, item_type, item_id)
        );
        CREATE TABLE IF NOT EXISTS clip_evaluations (
            id TEXT PRIMARY KEY,
            clip_id TEXT NOT NULL,
            job_id TEXT DEFAULT '',
            decision TEXT DEFAULT '',
            rejection_reasons TEXT DEFAULT '[]',
            correction_notes TEXT DEFAULT '',
            edit_time_seconds INTEGER DEFAULT 0,
            pipeline_version TEXT DEFAULT '',
            config_snapshot TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS missed_moments (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            video_id TEXT DEFAULT '',
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            notes TEXT DEFAULT '',
            generated_clip_id TEXT,
            created_at TEXT
        );
        """)
        # ── Performance indexes ───────────────────────────────────────────────
        # These are safe to CREATE IF NOT EXISTS on every startup.
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_candidates_job_id    ON candidates(job_id);
            CREATE INDEX IF NOT EXISTS idx_candidates_video_id  ON candidates(video_id);
            CREATE INDEX IF NOT EXISTS idx_clips_job_id         ON clips(job_id);
            CREATE INDEX IF NOT EXISTS idx_clips_candidate_id   ON clips(candidate_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status          ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_created_at      ON jobs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_videos_path          ON videos(path);
            CREATE INDEX IF NOT EXISTS idx_videos_job_id        ON videos(job_id);
            CREATE INDEX IF NOT EXISTS idx_pt_job_id            ON pipeline_timings(job_id);
            CREATE INDEX IF NOT EXISTS idx_pubs_clip_id         ON publications(clip_id);
            CREATE INDEX IF NOT EXISTS idx_pubs_status          ON publications(status);
            CREATE INDEX IF NOT EXISTS idx_pubs_creator_id      ON publications(creator_id);
            CREATE INDEX IF NOT EXISTS idx_prepub_clip_id       ON prepublish_decisions(clip_id);
            CREATE INDEX IF NOT EXISTS idx_coll_items_coll     ON collection_items(collection_id);
            CREATE INDEX IF NOT EXISTS idx_coll_items_item     ON collection_items(item_id);
            CREATE INDEX IF NOT EXISTS idx_clip_evals_clip_id  ON clip_evaluations(clip_id);
            CREATE INDEX IF NOT EXISTS idx_clip_evals_job_id   ON clip_evaluations(job_id);
            CREATE INDEX IF NOT EXISTS idx_missed_job_id       ON missed_moments(job_id);
        """)

        # Add columns that may not exist in older DB instances
        _add_column_if_missing(conn, "clips", "review_notes", "TEXT")
        _add_column_if_missing(conn, "job_queue", "result", "TEXT")
        _add_column_if_missing(conn, "videos", "creator_slug", "TEXT")
        _add_column_if_missing(conn, "videos", "video_slug", "TEXT")
        _add_column_if_missing(conn, "videos", "source_url", "TEXT")
        _add_column_if_missing(conn, "videos", "source_platform", "TEXT")
        _add_column_if_missing(conn, "videos", "source_title", "TEXT")
        # Caption system
        _add_column_if_missing(conn, "clips", "caption_data", "TEXT")
        _add_column_if_missing(conn, "clips", "caption_settings", "TEXT")
        # Enhanced candidate analysis (2026-09-09)
        _add_column_if_missing(conn, "candidates", "emotion_score", "REAL DEFAULT 0.0")
        _add_column_if_missing(conn, "candidates", "retention_score", "REAL DEFAULT 0.0")
        _add_column_if_missing(conn, "candidates", "importance_score", "REAL DEFAULT 0.0")
        _add_column_if_missing(conn, "candidates", "hook_time", "REAL DEFAULT 0.0")
        _add_column_if_missing(conn, "candidates", "virality_reasons", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "candidates", "smart_start", "REAL")
        _add_column_if_missing(conn, "candidates", "smart_end", "REAL")
        _add_column_if_missing(conn, "candidates", "series_id", "TEXT")
        _add_column_if_missing(conn, "candidates", "series_part", "INTEGER DEFAULT 0")
        # Future: social metrics prediction loop
        _add_column_if_missing(conn, "post_metrics", "predicted_virality_score", "REAL")
        _add_column_if_missing(conn, "post_metrics", "actual_vs_predicted_delta", "REAL")
        # Creator system (2026-09-09)
        _add_column_if_missing(conn, "jobs", "creator_id", "TEXT")
        _add_column_if_missing(conn, "videos", "creator_id", "TEXT")
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_creator_id ON videos(creator_id)")
        except Exception:
            pass
        _add_column_if_missing(conn, "videos", "thumbnail_path", "TEXT")
        # Performance optimization (2026-09-10)
        _add_column_if_missing(conn, "videos", "words_json", "TEXT")
        _add_column_if_missing(conn, "videos", "proxy_path", "TEXT")
        _add_column_if_missing(conn, "jobs", "error_category", "TEXT")
        _add_column_if_missing(conn, "pipeline_timings", "llm_tokens_used", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "pipeline_timings", "llm_cost_usd", "REAL DEFAULT 0.0")
        # Quality evaluation sprint (2026-09-15)
        _add_column_if_missing(conn, "jobs", "pipeline_snapshot", "TEXT")
        # YouTube upload tables (2026-09-17)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS yt_upload_sessions (
            id TEXT PRIMARY KEY,
            pub_id TEXT NOT NULL,
            clip_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            title TEXT,
            description TEXT,
            tags TEXT DEFAULT '[]',
            is_for_kids INTEGER DEFAULT 0,
            session_url TEXT,
            status TEXT DEFAULT 'pending',
            remote_video_id TEXT,
            remote_process_status TEXT,
            remote_privacy_status TEXT,
            bytes_sent INTEGER DEFAULT 0,
            file_size INTEGER,
            file_path TEXT,
            file_hash TEXT,
            attempts INTEGER DEFAULT 0,
            last_attempt_at TEXT,
            error_message TEXT,
            error_code TEXT,
            locked_at TEXT,
            locked_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (pub_id) REFERENCES publications(id),
            FOREIGN KEY (clip_id) REFERENCES clips(id),
            UNIQUE (pub_id)
        );
        CREATE TABLE IF NOT EXISTS yt_oauth_state (
            state TEXT PRIMARY KEY,
            code_verifier TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_yt_sessions_status ON yt_upload_sessions(status);
        CREATE INDEX IF NOT EXISTS idx_yt_sessions_pub_id ON yt_upload_sessions(pub_id);
        """)
        _add_column_if_missing(conn, "social_accounts", "channel_name", "TEXT")
        # Visibility / privacy columns (2026-09-18)
        _add_column_if_missing(conn, "yt_upload_sessions", "privacy_status", "TEXT DEFAULT 'private'")
        _add_column_if_missing(conn, "upload_batch_items", "privacy_status", "TEXT DEFAULT 'private'")
        _add_column_if_missing(conn, "upload_batches", "approved_privacy", "TEXT DEFAULT 'private'")
        # Packages & batch upload tables (2026-09-18)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS clip_packages (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clip_package_items (
            id TEXT PRIMARY KEY,
            package_id TEXT NOT NULL REFERENCES clip_packages(id) ON DELETE CASCADE,
            pub_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            UNIQUE(package_id, pub_id)
        );
        CREATE TABLE IF NOT EXISTS upload_batches (
            id TEXT PRIMARY KEY,
            name TEXT,
            channel_id TEXT,
            idempotency_key TEXT UNIQUE,
            paused INTEGER DEFAULT 0,
            total_items INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS upload_batch_items (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES upload_batches(id) ON DELETE CASCADE,
            pub_id TEXT NOT NULL,
            session_id TEXT,
            added_at TEXT NOT NULL,
            UNIQUE(batch_id, pub_id)
        );
        CREATE INDEX IF NOT EXISTS idx_pkg_items_pkg ON clip_package_items(package_id);
        CREATE INDEX IF NOT EXISTS idx_batch_items_batch ON upload_batch_items(batch_id);
        """)
        # Run migration: link existing videos to creator records
        _migrate_creators(conn)


def _add_column_if_missing(conn, table: str, column: str, coltype: str):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    except Exception:
        pass


def new_id():
    return str(uuid.uuid4())


def now():
    return datetime.utcnow().isoformat()


# ── Transcript cache helpers ──────────────────────────────────────────────────

def get_cached_words(video_id: str) -> list[dict] | None:
    """Return cached word-level transcript for this video_id, or None."""
    with db() as conn:
        row = conn.execute(
            "SELECT words_json FROM videos WHERE id=?", (video_id,)
        ).fetchone()
    if row and row["words_json"]:
        try:
            return json.loads(row["words_json"])
        except Exception:
            return None
    return None


def get_cached_words_by_path(video_path: str) -> list[dict] | None:
    """Return cached words from any previously processed video with the same path."""
    with db() as conn:
        row = conn.execute(
            "SELECT words_json FROM videos WHERE path=? AND words_json IS NOT NULL LIMIT 1",
            (video_path,)
        ).fetchone()
    if row and row["words_json"]:
        try:
            return json.loads(row["words_json"])
        except Exception:
            return None
    return None


def get_proxy_by_path(video_path: str) -> str | None:
    """Return proxy path from any previously processed video with the same source."""
    with db() as conn:
        row = conn.execute(
            "SELECT proxy_path FROM videos WHERE path=? AND proxy_path IS NOT NULL LIMIT 1",
            (video_path,)
        ).fetchone()
    return row["proxy_path"] if row and row["proxy_path"] else None


def save_words_cache(video_id: str, words: list[dict]) -> None:
    """Persist word-level transcript data for future reuse."""
    with db() as conn:
        conn.execute(
            "UPDATE videos SET words_json=? WHERE id=?",
            (json.dumps(words), video_id)
        )


def save_proxy_path(video_id: str, proxy_path: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE videos SET proxy_path=? WHERE id=?",
            (proxy_path, video_id)
        )


# ── Pipeline timing helpers ───────────────────────────────────────────────────

def save_pipeline_timings(job_id: str, rows: list[dict]) -> None:
    """Persist timing rows from PipelineTimer.to_rows()."""
    ts = now()
    with db() as conn:
        for r in rows:
            conn.execute(
                """INSERT INTO pipeline_timings
                   (job_id, stage, start_ts, end_ts, duration_s, status, meta,
                    llm_tokens_used, llm_cost_usd, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (job_id, r["stage"], r["start_ts"], r["end_ts"],
                 r["duration_s"], r["status"], r["meta"],
                 r.get("llm_tokens_used", 0), r.get("llm_cost_usd", 0.0), ts)
            )


def get_pipeline_timings(job_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_timings WHERE job_id=? ORDER BY start_ts",
            (job_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def create_job(source_path, mode, target_clips, target_platforms, creator, content_type,
               preset_id: str = None, pipeline_snapshot: dict = None):
    jid = preset_id or new_id()
    ts = now()
    snap_str = json.dumps(pipeline_snapshot or {})
    with db() as conn:
        if preset_id:
            # On retry the row already exists — skip INSERT and return existing id.
            existing = conn.execute("SELECT id FROM jobs WHERE id=?", (jid,)).fetchone()
            if existing:
                return jid
        conn.execute(
            """INSERT INTO jobs
               (id, source_path, status, mode, target_clips, target_platforms,
                creator, content_type, created_at, updated_at, error, metadata,
                pipeline_snapshot)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, source_path, "QUEUED", mode, target_clips,
             json.dumps(target_platforms), creator, content_type, ts, ts, None, "{}",
             snap_str)
        )
    return jid


def update_job(job_id, status=None, error=None, metadata=None, error_category=None):
    sets, vals = [], []
    if status:
        sets.append("status=?"); vals.append(status)
    if error is not None:
        sets.append("error=?"); vals.append(error)
    if metadata is not None:
        sets.append("metadata=?"); vals.append(json.dumps(metadata))
    if error_category is not None:
        sets.append("error_category=?"); vals.append(error_category)
    sets.append("updated_at=?"); vals.append(now())
    vals.append(job_id)
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?", vals)


def create_video(job_id, path, duration_s, fps, width, height, size_bytes):
    vid = new_id()
    with db() as conn:
        conn.execute(
            """INSERT INTO videos
               (id, job_id, path, duration_s, fps, width, height, size_bytes,
                rights_verified, transcript, audio_path, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (vid, job_id, path, duration_s, fps, width, height, size_bytes, 1, None, None, now())
        )
    return vid


_VIDEO_COLS = frozenset({
    "path", "duration_s", "fps", "width", "height", "size_bytes",
    "rights_verified", "transcript", "audio_path",
    "creator_slug", "video_slug", "source_url", "source_platform", "source_title",
    "words_json", "proxy_path", "creator_id", "thumbnail_path",
})


def update_video(video_id, **kwargs):
    sets, vals = [], []
    for k, v in kwargs.items():
        if k not in _VIDEO_COLS:
            raise ValueError(f"update_video: unknown column '{k}'")
        sets.append(f"{k}=?")
        vals.append(v if not isinstance(v, (dict, list)) else json.dumps(v))
    vals.append(video_id)
    with db() as conn:
        conn.execute(f"UPDATE videos SET {','.join(sets)} WHERE id=?", vals)


def create_candidate(job_id, video_id, start_s, end_s, score=0.0, score_breakdown=None):
    cid = new_id()
    with db() as conn:
        conn.execute(
            """INSERT INTO candidates
               (id, job_id, video_id, start_s, end_s, score, score_breakdown,
                virality_score, hook_score, visual_score, audio_score,
                platform_scores, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, job_id, video_id, start_s, end_s, score,
             json.dumps(score_breakdown or {}), 0.0, 0.0, 0.0, 0.0, "{}", "DETECTED", now())
        )
    return cid


_CANDIDATE_COLS = frozenset({
    "start_s", "end_s", "score", "score_breakdown",
    "virality_score", "hook_score", "visual_score", "audio_score",
    "platform_scores", "status",
    "emotion_score", "retention_score", "importance_score",
    "hook_time", "virality_reasons", "smart_start", "smart_end",
    "series_id", "series_part",
})


def update_candidate(candidate_id, **kwargs):
    sets, vals = [], []
    for k, v in kwargs.items():
        if k not in _CANDIDATE_COLS:
            raise ValueError(f"update_candidate: unknown column '{k}'")
        sets.append(f"{k}=?")
        vals.append(v if not isinstance(v, (dict, list)) else json.dumps(v))
    vals.append(candidate_id)
    with db() as conn:
        conn.execute(f"UPDATE candidates SET {','.join(sets)} WHERE id=?", vals)


def create_clip(job_id, candidate_id):
    clid = new_id()
    with db() as conn:
        conn.execute(
            """INSERT INTO clips
               (id, job_id, candidate_id, output_path, captioned_path,
                width, height, fps, duration_s, file_size,
                technical_qa, visual_qa, qa_notes, platform_fit_scores,
                prepublish_decision, prepublish_score, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (clid, job_id, candidate_id, None, None, None, None, None, None, None,
             "PENDING", "PENDING", "{}", "{}", "PENDING", 0.0, now())
        )
    return clid


_CLIP_COLS = frozenset({
    "output_path", "captioned_path", "width", "height", "fps", "duration_s", "file_size",
    "technical_qa", "visual_qa", "qa_notes", "platform_fit_scores",
    "prepublish_decision", "prepublish_score",
    "caption_data", "caption_settings", "review_notes",
})


def update_clip(clip_id, **kwargs):
    sets, vals = [], []
    for k, v in kwargs.items():
        if k not in _CLIP_COLS:
            raise ValueError(f"update_clip: unknown column '{k}'")
        sets.append(f"{k}=?")
        vals.append(v if not isinstance(v, (dict, list)) else json.dumps(v))
    vals.append(clip_id)
    with db() as conn:
        conn.execute(f"UPDATE clips SET {','.join(sets)} WHERE id=?", vals)


def log_skill_run(job_id, skill_name, input_summary, output, score, duration_ms, status="OK"):
    with db() as conn:
        conn.execute(
            "INSERT INTO skill_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id(), job_id, skill_name, input_summary, json.dumps(output), score, duration_ms, status, now())
        )


def create_prepublish_decision(clip_id, job_id, decision, score, technical_qa, visual_qa,
                                rights_verified, platform_fit_scores, blocking_reasons):
    pid = new_id()
    with db() as conn:
        conn.execute(
            "INSERT INTO prepublish_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, clip_id, job_id, decision, score, technical_qa, visual_qa,
             int(rights_verified), json.dumps(platform_fit_scores),
             json.dumps(blocking_reasons), now())
        )
    return pid


def get_job_clips(job_id):
    with db() as conn:
        return conn.execute("SELECT * FROM clips WHERE job_id=?", (job_id,)).fetchall()


def get_job_candidates(job_id):
    with db() as conn:
        return conn.execute("SELECT * FROM candidates WHERE job_id=? ORDER BY score DESC", (job_id,)).fetchall()


# ── Caption helpers ────────────────────────────────────────────────────────────

def get_clip_captions(clip_id: str) -> tuple[dict | None, dict | None]:
    """Return (caption_data, caption_settings) dicts for a clip, or (None, None)."""
    with db() as conn:
        row = conn.execute(
            "SELECT caption_data, caption_settings FROM clips WHERE id=?", (clip_id,)
        ).fetchone()
    if not row:
        return None, None
    data = json.loads(row["caption_data"]) if row["caption_data"] else None
    settings = json.loads(row["caption_settings"]) if row["caption_settings"] else None
    return data, settings


def update_clip_captions(clip_id: str,
                         caption_data: dict | None = None,
                         caption_settings: dict | None = None):
    sets, vals = [], []
    if caption_data is not None:
        sets.append("caption_data=?")
        vals.append(json.dumps(caption_data))
    if caption_settings is not None:
        sets.append("caption_settings=?")
        vals.append(json.dumps(caption_settings))
    if not sets:
        return
    vals.append(clip_id)
    with db() as conn:
        conn.execute(f"UPDATE clips SET {','.join(sets)} WHERE id=?", vals)


# ── Series helpers ─────────────────────────────────────────────────────────────

def create_series(job_id, video_id, series_score, total_parts, series_reasons,
                  original_start, original_end, title) -> str:
    sid = new_id()
    with db() as conn:
        conn.execute(
            "INSERT INTO clip_series VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, job_id, video_id, series_score, total_parts,
             json.dumps(series_reasons), original_start, original_end, title, now())
        )
    return sid


def _migrate_creators(conn):
    """One-time migration: create Creator records from existing job.creator names."""
    SKIP = {"unknown", "local", "", "none"}
    rows = conn.execute("""
        SELECT DISTINCT j.creator, v.id as vid, v.creator_slug
        FROM jobs j JOIN videos v ON v.job_id = j.id
        WHERE v.creator_id IS NULL AND j.creator_id IS NULL
        AND j.creator IS NOT NULL
    """).fetchall()
    for row in rows:
        raw_name = (row["creator"] or "").strip()
        if not raw_name or raw_name.lower() in SKIP:
            continue
        name = raw_name.title() if raw_name.islower() else raw_name
        existing = conn.execute(
            "SELECT id FROM creators WHERE name=? COLLATE NOCASE", (name,)
        ).fetchone()
        if existing:
            cid = existing["id"]
        else:
            cid = str(uuid.uuid4())
            ts = datetime.utcnow().isoformat()
            color = _avatar_color(name)
            conn.execute(
                "INSERT OR IGNORE INTO creators (id,name,display_name,avatar_color,platform,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (cid, name, name, color, row["creator_slug"] or "", ts, ts)
            )
        conn.execute("UPDATE videos SET creator_id=? WHERE id=?", (cid, row["vid"]))
        conn.execute(
            "UPDATE jobs SET creator_id=? WHERE id=(SELECT job_id FROM videos WHERE id=?)",
            (cid, row["vid"])
        )


def _avatar_color(name: str) -> str:
    import hashlib
    COLORS = ["#3b82f6","#8b5cf6","#ec4899","#ef4444","#f97316",
              "#eab308","#22c55e","#06b6d4","#14b8a6","#a855f7"]
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return COLORS[h % len(COLORS)]


# ── Creator helpers ────────────────────────────────────────────────────────────

def create_creator(name: str, display_name: str = None, handle: str = None,
                   platform: str = None, channel_url: str = None,
                   external_channel_id: str = None, avatar_color: str = None) -> str:
    cid = new_id()
    ts = now()
    color = avatar_color or _avatar_color(name)
    with db() as conn:
        conn.execute(
            """INSERT INTO creators (id,name,display_name,handle,avatar_color,platform,
               channel_url,external_channel_id,is_favorite,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,0,?,?)""",
            (cid, name, display_name or name, handle or "", color,
             platform or "", channel_url or "", external_channel_id or "", ts, ts)
        )
    return cid


def get_creators() -> list:
    with db() as conn:
        rows = conn.execute("SELECT * FROM creators ORDER BY is_favorite DESC, name ASC").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            stats = conn.execute("""
                SELECT COUNT(DISTINCT v.id) as video_count,
                       COUNT(DISTINCT cl.id) as clip_count,
                       MAX(j.updated_at) as last_activity
                FROM videos v
                JOIN jobs j ON v.job_id = j.id
                LEFT JOIN candidates ca ON ca.video_id = v.id
                LEFT JOIN clips cl ON cl.candidate_id = ca.id
                WHERE v.creator_id=?
            """, (d["id"],)).fetchone()
            d.update(dict(stats) if stats else {})
            # count processing
            d["processing_count"] = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE creator_id=? AND status NOT IN ('COMPLETED','FAILED')",
                (d["id"],)
            ).fetchone()[0]
            result.append(d)
        return result


def get_creator(creator_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM creators WHERE id=?", (creator_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        stats = conn.execute("""
            SELECT COUNT(DISTINCT v.id) as video_count,
                   COUNT(DISTINCT cl.id) as clip_count,
                   MAX(COALESCE(ca.virality_score,0)) as best_score,
                   AVG(CASE WHEN ca.virality_score>0 THEN ca.virality_score END) as avg_score
            FROM videos v
            JOIN jobs j ON v.job_id = j.id
            LEFT JOIN candidates ca ON ca.video_id = v.id
            LEFT JOIN clips cl ON cl.candidate_id = ca.id
            WHERE v.creator_id=?
        """, (creator_id,)).fetchone()
        d.update(dict(stats) if stats else {})
        return d


_CREATOR_COLS = frozenset({
    "name", "display_name", "handle", "avatar_color",
    "platform", "channel_url", "external_channel_id", "is_favorite",
})


def update_creator(creator_id: str, **kwargs):
    sets, vals = [], []
    for k, v in kwargs.items():
        if k not in _CREATOR_COLS:
            raise ValueError(f"update_creator: unknown column '{k}'")
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("updated_at=?"); vals.append(now())
    vals.append(creator_id)
    with db() as conn:
        conn.execute(f"UPDATE creators SET {','.join(sets)} WHERE id=?", vals)


def delete_creator(creator_id: str, action: str = "unassign"):
    """action: 'unassign' (keep videos, set creator_id=NULL) or 'delete_all'"""
    with db() as conn:
        if action == "delete_all":
            # Mark any in-progress jobs as failed before cascade-deleting their records
            conn.execute(
                "UPDATE jobs SET status='failed', error='Creator deleted' "
                "WHERE creator_id=? AND LOWER(status) NOT IN ('completed','failed')",
                (creator_id,)
            )
            conn.execute(
                "DELETE FROM job_queue WHERE id IN "
                "(SELECT id FROM jobs WHERE creator_id=?)", (creator_id,)
            )
            vids = conn.execute(
                "SELECT id FROM videos WHERE creator_id=?", (creator_id,)
            ).fetchall()
            for v in vids:
                _delete_video_cascade(conn, v["id"])
            # Clean up any orphaned publication records not caught by clip cascade
            conn.execute("DELETE FROM publications WHERE creator_id=?", (creator_id,))
        else:
            conn.execute("UPDATE videos SET creator_id=NULL WHERE creator_id=?", (creator_id,))
            conn.execute("UPDATE jobs SET creator_id=NULL WHERE creator_id=?", (creator_id,))
            conn.execute("UPDATE publications SET creator_id=NULL WHERE creator_id=?", (creator_id,))
        conn.execute("DELETE FROM creators WHERE id=?", (creator_id,))


def get_creator_impact(creator_id: str) -> dict:
    """Return real content counts for a creator. Used by the deletion confirmation UI."""
    import os
    with db() as conn:
        video_count = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE creator_id=?", (creator_id,)
        ).fetchone()[0]
        clip_count = conn.execute("""
            SELECT COUNT(DISTINCT cl.id) FROM clips cl
            JOIN candidates ca ON cl.candidate_id = ca.id
            JOIN videos v ON ca.video_id = v.id
            WHERE v.creator_id = ?
        """, (creator_id,)).fetchone()[0]
        series_count = conn.execute("""
            SELECT COUNT(*) FROM clip_series
            WHERE video_id IN (SELECT id FROM videos WHERE creator_id=?)
        """, (creator_id,)).fetchone()[0]
        pub_count = conn.execute(
            "SELECT COUNT(*) FROM publications WHERE creator_id=?", (creator_id,)
        ).fetchone()[0]
        active_job_count = conn.execute("""
            SELECT COUNT(*) FROM jobs
            WHERE creator_id=? AND LOWER(status) NOT IN ('completed','failed')
        """, (creator_id,)).fetchone()[0]
        video_rows = conn.execute(
            "SELECT path, proxy_path FROM videos WHERE creator_id=?", (creator_id,)
        ).fetchall()

    storage_bytes = 0
    for vr in video_rows:
        for p in [vr["path"], vr["proxy_path"]]:
            if p:
                try:
                    storage_bytes += os.path.getsize(p)
                except Exception:
                    pass

    return {
        "video_count": video_count,
        "clip_count": clip_count,
        "series_count": series_count,
        "publication_count": pub_count,
        "active_job_count": active_job_count,
        "storage_bytes": storage_bytes,
    }


def assign_video_creator(video_id: str, creator_id: str | None):
    with db() as conn:
        conn.execute("UPDATE videos SET creator_id=? WHERE id=?", (creator_id, video_id))
        # Also update the parent job
        conn.execute(
            "UPDATE jobs SET creator_id=? WHERE id=(SELECT job_id FROM videos WHERE id=?)",
            (creator_id, video_id)
        )


def get_all_videos(creator_id: str = None, status: str = None, search: str = None,
                   platform: str = None, sort: str = "newest",
                   limit: int = 50, offset: int = 0,
                   virality_min: float = None, virality_max: float = None,
                   date_from: str = None, date_to: str = None,
                   collection_id: str = None) -> list:
    conditions = []
    params = []
    joins = ""
    if creator_id == "__unassigned__":
        conditions.append("v.creator_id IS NULL")
    elif creator_id:
        conditions.append("v.creator_id=?"); params.append(creator_id)
    if status:
        conditions.append("j.status=?"); params.append(status.upper())
    if platform:
        conditions.append("v.source_platform=?"); params.append(platform)
    if search:
        like = f"%{search}%"
        conditions.append("(v.source_title LIKE ? OR j.creator LIKE ? OR v.source_url LIKE ? OR cr.name LIKE ?)")
        params += [like, like, like, like]
    if date_from:
        conditions.append("j.created_at >= ?"); params.append(date_from)
    if date_to:
        conditions.append("j.created_at <= ?"); params.append(date_to + "T23:59:59")
    if collection_id:
        joins = "JOIN collection_items ci ON ci.item_id = v.id AND ci.item_type='video' AND ci.collection_id=?"
        params.insert(0, collection_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = {
        "newest": "j.created_at DESC",
        "oldest": "j.created_at ASC",
        "virality": "best_virality DESC NULLS LAST",
        "retention": "MAX(ca.retention_score) DESC NULLS LAST",
        "clips": "clip_count DESC",
        "duration": "v.duration_s DESC NULLS LAST",
        "creator": "cr.name ASC NULLS LAST",
    }.get(sort, "j.created_at DESC")

    # For HAVING filters (aggregates)
    having_conditions = []
    if virality_min is not None:
        having_conditions.append(f"best_virality >= {float(virality_min)}")
    if virality_max is not None:
        having_conditions.append(f"best_virality <= {float(virality_max)}")
    having = ("HAVING " + " AND ".join(having_conditions)) if having_conditions else ""

    with db() as conn:
        rows = conn.execute(f"""
            SELECT v.*, j.id as job_id, j.status as job_status, j.creator as job_creator,
                   j.creator_id, j.created_at as job_created_at, j.error as job_error,
                   cr.name as creator_name, cr.avatar_color,
                   COUNT(DISTINCT cl.id) as clip_count,
                   MAX(ca.virality_score) as best_virality
            FROM videos v
            {joins}
            JOIN jobs j ON v.job_id = j.id
            LEFT JOIN creators cr ON v.creator_id = cr.id
            LEFT JOIN candidates ca ON ca.video_id = v.id
            LEFT JOIN clips cl ON cl.candidate_id = ca.id
            {where}
            GROUP BY v.id
            {having}
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
        return [dict(r) for r in rows]


def get_bulk_delete_impact(video_ids: list) -> dict:
    if not video_ids:
        return {"video_count": 0, "clip_count": 0, "series_count": 0,
                "publication_count": 0, "storage_bytes": 0}
    with db() as conn:
        ph = ','.join('?' * len(video_ids))
        clip_count = conn.execute(
            f"SELECT COUNT(DISTINCT cl.id) FROM clips cl "
            f"JOIN candidates ca ON cl.candidate_id=ca.id "
            f"WHERE ca.video_id IN ({ph})", video_ids).fetchone()[0]
        series_count = conn.execute(
            f"SELECT COUNT(*) FROM clip_series WHERE video_id IN ({ph})", video_ids).fetchone()[0]
        pub_count = conn.execute(
            f"SELECT COUNT(DISTINCT p.id) FROM publications p "
            f"JOIN clips cl ON p.clip_id=cl.id "
            f"JOIN candidates ca ON cl.candidate_id=ca.id "
            f"WHERE ca.video_id IN ({ph})", video_ids).fetchone()[0]
        storage = conn.execute(
            f"SELECT COALESCE(SUM(size_bytes),0) FROM videos WHERE id IN ({ph})",
            video_ids).fetchone()[0]
        active_jobs = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE id IN "
            f"(SELECT job_id FROM videos WHERE id IN ({ph})) "
            f"AND status NOT IN ('COMPLETED','FAILED','completed','failed')",
            video_ids).fetchone()[0]
    return {
        "video_count": len(video_ids),
        "clip_count": clip_count,
        "series_count": series_count,
        "publication_count": pub_count,
        "storage_bytes": storage,
        "active_job_count": active_jobs,
    }


# ── Collections ────────────────────────────────────────────────────────────────

def get_all_collections() -> list:
    with db() as conn:
        rows = conn.execute("""
            SELECT c.*, COUNT(DISTINCT ci.id) as item_count
            FROM collections c
            LEFT JOIN collection_items ci ON ci.collection_id = c.id
            GROUP BY c.id
            ORDER BY c.name ASC
        """).fetchall()
        return [dict(r) for r in rows]


def get_collection(collection_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("""
            SELECT c.*, COUNT(DISTINCT ci.id) as item_count
            FROM collections c
            LEFT JOIN collection_items ci ON ci.collection_id = c.id
            WHERE c.id=?
            GROUP BY c.id
        """, (collection_id,)).fetchone()
        return dict(row) if row else None


def create_collection(name: str, description: str = "", color: str = "#3b82f6") -> str:
    cid = new_id()
    ts = now()
    with db() as conn:
        conn.execute(
            "INSERT INTO collections (id, name, description, color, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (cid, name, description, color, ts, ts))
    return cid


def update_collection(collection_id: str, name: str = None, description: str = None,
                      color: str = None) -> bool:
    fields, params = [], []
    if name is not None:
        fields.append("name=?"); params.append(name)
    if description is not None:
        fields.append("description=?"); params.append(description)
    if color is not None:
        fields.append("color=?"); params.append(color)
    if not fields:
        return False
    fields.append("updated_at=?"); params.append(now())
    params.append(collection_id)
    with db() as conn:
        conn.execute(f"UPDATE collections SET {','.join(fields)} WHERE id=?", params)
    return True


def delete_collection(collection_id: str):
    with db() as conn:
        conn.execute("DELETE FROM collection_items WHERE collection_id=?", (collection_id,))
        conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))


def add_collection_items(collection_id: str, items: list) -> int:
    """items: list of {item_type, item_id}. Returns count added."""
    added = 0
    ts = now()
    with db() as conn:
        for item in items:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO collection_items "
                    "(id, collection_id, item_type, item_id, added_at) VALUES (?,?,?,?,?)",
                    (new_id(), collection_id, item["item_type"], item["item_id"], ts))
                added += 1
            except Exception:
                pass
    return added


def remove_collection_items(collection_id: str, items: list) -> int:
    """items: list of {item_type, item_id}. Returns count removed."""
    removed = 0
    with db() as conn:
        for item in items:
            cur = conn.execute(
                "DELETE FROM collection_items WHERE collection_id=? AND item_type=? AND item_id=?",
                (collection_id, item["item_type"], item["item_id"]))
            removed += cur.rowcount
    return removed


def get_collection_videos(collection_id: str, sort: str = "newest",
                          limit: int = 200) -> list:
    return get_all_videos(collection_id=collection_id, sort=sort, limit=limit)


def delete_clip_by_id(clip_id: str):
    import os
    with db() as conn:
        cl = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if not cl:
            return
        conn.execute(
            "DELETE FROM publication_metrics WHERE publication_id IN "
            "(SELECT id FROM publications WHERE clip_id=?)", (clip_id,))
        conn.execute("DELETE FROM publications WHERE clip_id=?", (clip_id,))
        conn.execute("DELETE FROM prepublish_decisions WHERE clip_id=?", (clip_id,))
        for p in [cl["captioned_path"], cl["output_path"]]:
            if p:
                try: os.remove(p)
                except Exception: pass
        conn.execute("DELETE FROM clips WHERE id=?", (clip_id,))


def delete_video_by_id(video_id: str, delete_clips: bool = True):
    with db() as conn:
        _delete_video_cascade(conn, video_id, delete_clips=delete_clips)


def _delete_video_cascade(conn, video_id: str, delete_clips: bool = True):
    import os
    v = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not v:
        return
    job_id = v["job_id"]

    # Gather all clip IDs for this video (needed to clean up FK deps)
    cands = conn.execute("SELECT id FROM candidates WHERE video_id=?", (video_id,)).fetchall()
    for ca in cands:
        clip_rows = conn.execute(
            "SELECT id, captioned_path, output_path FROM clips WHERE candidate_id=?", (ca["id"],)
        ).fetchall()
        for cl in clip_rows:
            cid = cl["id"]
            # publications deps
            conn.execute("DELETE FROM publication_audit_log WHERE publication_id IN "
                         "(SELECT id FROM publications WHERE clip_id=?)", (cid,))
            conn.execute("DELETE FROM publication_metrics WHERE publication_id IN "
                         "(SELECT id FROM publications WHERE clip_id=?)", (cid,))
            conn.execute("DELETE FROM publications WHERE clip_id=?", (cid,))
            # prepublish_decisions references both clip_id and job_id
            conn.execute("DELETE FROM prepublish_decisions WHERE clip_id=?", (cid,))
            if delete_clips:
                for p in [cl["captioned_path"], cl["output_path"]]:
                    if p:
                        try: os.remove(p)
                        except Exception: pass
        if delete_clips:
            conn.execute("DELETE FROM clips WHERE candidate_id=?", (ca["id"],))

    # skill_runs references job_id
    conn.execute("DELETE FROM skill_runs WHERE job_id=?", (job_id,))
    # job_queue entries (payload contains job_id but no FK — safe to clean up anyway)
    conn.execute("DELETE FROM job_queue WHERE id=?", (job_id,))

    if delete_clips:
        conn.execute("DELETE FROM candidates WHERE video_id=?", (video_id,))

    # Series linked to this video
    conn.execute("DELETE FROM clip_series WHERE video_id=?", (video_id,))

    # Delete video file, audio, and proxy
    for p in [v["path"], v["audio_path"], v["proxy_path"]]:
        if p:
            try: os.remove(p)
            except Exception: pass
    conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
    # Only delete job if no other videos reference it (shared job_id guard)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE job_id=?", (job_id,)
    ).fetchone()[0]
    if remaining == 0:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def get_job_series(job_id: str) -> list:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM clip_series WHERE job_id=? ORDER BY series_score DESC",
            (job_id,)
        ).fetchall()
        if not rows:
            return []
        result = []
        for s in rows:
            sd = dict(s)
            try:
                sd["series_reasons"] = json.loads(sd.get("series_reasons") or "[]")
            except Exception:
                sd["series_reasons"] = []
            raw_parts = conn.execute(
                "SELECT * FROM candidates WHERE series_id=? ORDER BY series_part ASC, start_s ASC",
                (sd["id"],)
            ).fetchall()
            grouped: dict = {}
            for p in raw_parts:
                pd = dict(p)
                pn = pd.get("series_part") or 1
                if pn not in grouped:
                    grouped[pn] = pd
                else:
                    grouped[pn]["start_s"] = min(grouped[pn]["start_s"], pd["start_s"])
                    grouped[pn]["end_s"] = max(grouped[pn]["end_s"], pd["end_s"])
            sd["parts"] = [grouped[k] for k in sorted(grouped.keys())]
            result.append(sd)
        return result


# ── Publication helpers ────────────────────────────────────────────────────────

SUPPORTED_PLATFORMS = ["tiktok", "youtube_shorts", "instagram_reels"]


def create_publication(clip_id: str, platform: str, creator_id: str = None,
                       video_id: str = None, series_id: str = None,
                       series_part: int = 0, publication_order: int = 0,
                       status: str = "draft") -> str:
    pid = new_id()
    ts = now()
    with db() as conn:
        conn.execute(
            """INSERT INTO publications
               (id, clip_id, creator_id, video_id, series_id, series_part, platform,
                status, hashtags, platform_overrides, retry_count, publication_order,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
            (pid, clip_id, creator_id, video_id, series_id, series_part,
             platform, status, "[]", "{}", publication_order, ts, ts)
        )
    return pid


def _pub_row_to_dict(r: dict) -> dict:
    d = dict(r)
    for field in ("hashtags", "platform_overrides"):
        try:
            d[field] = json.loads(d.get(field) or ("[]" if field == "hashtags" else "{}"))
        except Exception:
            d[field] = [] if field == "hashtags" else {}
    try:
        d["virality_reasons"] = json.loads(d.get("virality_reasons") or "[]")
    except Exception:
        d["virality_reasons"] = []
    return d


_PUB_SELECT = """
    SELECT p.*,
           cl.captioned_path, cl.output_path, cl.duration_s AS clip_duration_s,
           cl.prepublish_decision,
           ca.virality_score, ca.retention_score, ca.importance_score,
           ca.virality_reasons, ca.start_s, ca.end_s,
           cr.name AS creator_name, cr.avatar_color,
           v.source_title, v.thumbnail_path, v.creator_slug, v.video_slug
    FROM publications p
    JOIN clips cl ON p.clip_id = cl.id
    JOIN candidates ca ON cl.candidate_id = ca.id
    LEFT JOIN creators cr ON p.creator_id = cr.id
    LEFT JOIN videos v ON p.video_id = v.id
"""


def get_publications(status: str = None, creator_id: str = None, platform: str = None,
                     search: str = None, sort: str = "newest",
                     limit: int = 50, offset: int = 0,
                     series_only: bool = False, standalone_only: bool = False) -> list:
    conditions, params = [], []
    if status:
        conditions.append("p.status=?"); params.append(status)
    if creator_id:
        conditions.append("p.creator_id=?"); params.append(creator_id)
    if platform:
        conditions.append("p.platform=?"); params.append(platform)
    if series_only:
        conditions.append("p.series_id IS NOT NULL")
    elif standalone_only:
        conditions.append("p.series_id IS NULL")
    if search:
        like = f"%{search}%"
        conditions.append("(p.title LIKE ? OR p.caption LIKE ? OR cr.name LIKE ? OR v.source_title LIKE ?)")
        params += [like, like, like, like]
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = {
        "newest": "p.created_at DESC",
        "oldest": "p.created_at ASC",
        "virality": "ca.virality_score DESC",
        "scheduled": "p.scheduled_at ASC NULLS LAST",
        "creator": "cr.name ASC",
        "status": "p.status ASC",
    }.get(sort, "p.created_at DESC")
    with db() as conn:
        rows = conn.execute(
            f"{_PUB_SELECT} {where} ORDER BY p.series_id ASC, p.publication_order ASC, {order} LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        return [_pub_row_to_dict(r) for r in rows]


def get_publication(pub_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            f"{_PUB_SELECT} WHERE p.id=?", (pub_id,)
        ).fetchone()
        return _pub_row_to_dict(row) if row else None


_PUBLICATION_COLS = frozenset({
    "status", "title", "caption", "hashtags", "platform_overrides",
    "scheduled_at", "published_at", "external_post_id", "external_url",
    "error_message", "retry_count", "next_retry_at", "publication_order", "notes",
})


def update_publication(pub_id: str, **kwargs):
    sets, vals = [], []
    for k, v in kwargs.items():
        if k not in _PUBLICATION_COLS:
            raise ValueError(f"update_publication: unknown column '{k}'")
        sets.append(f"{k}=?")
        vals.append(v if not isinstance(v, (dict, list)) else json.dumps(v))
    sets.append("updated_at=?"); vals.append(now())
    vals.append(pub_id)
    with db() as conn:
        conn.execute(f"UPDATE publications SET {','.join(sets)} WHERE id=?", vals)


def delete_publication(pub_id: str):
    with db() as conn:
        conn.execute("DELETE FROM publications WHERE id=?", (pub_id,))


def get_publications_for_clip(clip_id: str) -> list:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM publications WHERE clip_id=? ORDER BY platform ASC", (clip_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_publication_stats() -> dict:
    with db() as conn:
        totals = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM publications GROUP BY status"
        ).fetchall()
    stats = {r["status"]: r["cnt"] for r in totals}
    stats["total"] = sum(stats.values())
    for s in ("ready", "draft", "published", "scheduled", "failed", "cancelled"):
        stats.setdefault(s, 0)
    return stats


def log_publication_audit(pub_id: str, action: str, details: str = None):
    with db() as conn:
        conn.execute(
            "INSERT INTO publication_audit_log (publication_id, action, details, created_at) VALUES (?,?,?,?)",
            (pub_id, action, details, now())
        )


def add_publication_metrics(pub_id: str, **kwargs) -> str:
    mid = new_id()
    fields = ["id", "publication_id", "collected_at"]
    vals = [mid, pub_id, now()]
    for f in ("views", "likes", "comments", "shares", "saves",
              "avg_watch_time_s", "completion_rate", "followers_generated", "source"):
        if f in kwargs:
            fields.append(f); vals.append(kwargs[f])
    placeholders = ",".join(["?"] * len(vals))
    with db() as conn:
        conn.execute(
            f"INSERT INTO publication_metrics ({','.join(fields)}) VALUES ({placeholders})", vals
        )
    return mid


def generate_clip_metadata(clip_id: str) -> dict:
    with db() as conn:
        row = conn.execute("""
            SELECT ca.virality_reasons, ca.virality_score,
                   cr.name as creator_name, cr.handle,
                   v.source_title, v.source_platform,
                   cs.title as series_title
            FROM candidates ca
            JOIN clips cl ON cl.candidate_id = ca.id
            LEFT JOIN videos v ON ca.video_id = v.id
            LEFT JOIN creators cr ON v.creator_id = cr.id
            LEFT JOIN clip_series cs ON ca.series_id = cs.id
            WHERE cl.id=?
        """, (clip_id,)).fetchone()
    if not row:
        return {"title": "", "caption": "", "hashtags": []}
    d = dict(row)
    creator = d.get("creator_name") or "Creator"
    score = d.get("virality_score") or 0
    try:
        reasons = json.loads(d.get("virality_reasons") or "[]")
    except Exception:
        reasons = []
    return {
        "title": _suggest_title(creator, reasons, score, d.get("series_title"), d.get("source_title") or ""),
        "caption": _suggest_caption(creator, reasons, score),
        "hashtags": _suggest_hashtags(creator, reasons, d.get("source_platform")),
    }


def _suggest_title(creator, reasons, score, series_title=None, source_title=""):
    import random
    reason_lower = " ".join(reasons).lower()
    HOOK = ["This moment had everyone talking", "Nobody saw this coming",
            "Wait for the reaction", "This caught everyone off guard",
            "The moment everything changed"]
    EMOTIONAL = ["This moment hit different", "The reaction was priceless",
                 "This had the whole room going"]
    HIGH = ["Best moment of the stream", "This is why we watch",
            "Clip of the year material", "This clip is going viral"]
    if series_title:
        return f"{creator}: {series_title[:60]}"
    if "hook" in reason_lower or "opener" in reason_lower:
        pool = HOOK
    elif "emotion" in reason_lower or "reaction" in reason_lower:
        pool = EMOTIONAL
    elif score >= 85:
        pool = HIGH
    else:
        pool = HOOK
    base = random.choice(pool)
    if len(creator) < 20 and creator not in ("Creator", "unknown"):
        return f"{creator}: {base}"
    return base


def _suggest_caption(creator, reasons, score):
    import random
    reason_lower = " ".join(reasons).lower()
    if score >= 90:
        intros = ["This clip is insane 🔥", "Absolutely wild 🔥", "No way this happened 😱"]
    elif score >= 75:
        intros = ["You need to see this", "This moment right here", "Peak content 🔥"]
    else:
        intros = ["Clip of the day", "This one got me", "Don't miss this"]
    intro = random.choice(intros)
    if "funny" in reason_lower or "humor" in reason_lower:
        return f"{intro} 😂 The reactions say it all."
    elif "conflict" in reason_lower or "argument" in reason_lower:
        return f"{intro} Things escalated fast."
    elif "revelation" in reason_lower or "reveal" in reason_lower:
        return f"{intro} The reveal at the end is everything."
    return f"{intro} Follow for more."


def _suggest_hashtags(creator, reasons, platform=None):
    tags = []
    if creator and creator not in ("Creator", "unknown", ""):
        slug = creator.lower().replace(" ", "").replace("-", "")
        tags.append(f"#{slug}")
    reason_lower = " ".join(reasons).lower()
    if "funny" in reason_lower or "humor" in reason_lower:
        tags += ["#funny", "#lol"]
    if "reaction" in reason_lower:
        tags += ["#reaction"]
    if "conflict" in reason_lower or "argument" in reason_lower:
        tags += ["#drama"]
    tags += ["#viral", "#fyp", "#foryou"]
    if platform in ("youtube", "youtube_shorts"):
        tags.append("#shorts")
    elif platform == "tiktok":
        tags.append("#tiktok")
    elif platform in ("instagram", "instagram_reels"):
        tags.append("#reels")
    seen, result = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t); result.append(t)
    return result[:12]


# ── Quality evaluation helpers ────────────────────────────────────────────────

def _parse_json_field(value, default):
    try:
        return json.loads(value or json.dumps(default))
    except Exception:
        return default


def upsert_evaluation(clip_id: str, **kwargs) -> str:
    """Create or update the human quality evaluation for a clip. Returns eval id."""
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM clip_evaluations WHERE clip_id=?", (clip_id,)
        ).fetchone()
        ts = now()
        if row:
            eval_id = row["id"]
            sets, vals = [], []
            for k, v in kwargs.items():
                sets.append(f"{k}=?")
                vals.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
            sets.append("updated_at=?")
            vals.append(ts)
            vals.append(eval_id)
            conn.execute(
                f"UPDATE clip_evaluations SET {','.join(sets)} WHERE id=?", vals
            )
        else:
            eval_id = new_id()
            conn.execute("""
                INSERT INTO clip_evaluations
                    (id, clip_id, job_id, decision, rejection_reasons, correction_notes,
                     edit_time_seconds, pipeline_version, config_snapshot, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                eval_id, clip_id,
                kwargs.get("job_id", ""),
                kwargs.get("decision", ""),
                json.dumps(kwargs.get("rejection_reasons", [])),
                kwargs.get("correction_notes", ""),
                int(kwargs.get("edit_time_seconds", 0)),
                kwargs.get("pipeline_version", ""),
                json.dumps(kwargs.get("config_snapshot", {})),
                ts, ts,
            ))
    return eval_id


def get_evaluation(clip_id: str) -> dict | None:
    """Return the evaluation record for a clip, or None if not yet evaluated."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM clip_evaluations WHERE clip_id=?", (clip_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["rejection_reasons"] = _parse_json_field(d.get("rejection_reasons"), [])
    d["config_snapshot"] = _parse_json_field(d.get("config_snapshot"), {})
    return d


def list_evaluations(job_id=None, decision=None, from_date=None, to_date=None,
                     limit=200, offset=0) -> list[dict]:
    conds, params = [], []
    if job_id:
        conds.append("e.job_id=?"); params.append(job_id)
    if decision:
        conds.append("e.decision=?"); params.append(decision)
    if from_date:
        conds.append("e.created_at>=?"); params.append(from_date)
    if to_date:
        conds.append("e.created_at<=?"); params.append(to_date + "T23:59:59")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    with db() as conn:
        rows = conn.execute(f"""
            SELECT e.*,
                   c.duration_s,
                   c.prepublish_decision AS clip_decision,
                   cand.virality_score, cand.hook_score,
                   v.source_title, v.source_url, v.creator_slug,
                   j.created_at AS job_created_at,
                   j.pipeline_snapshot
            FROM clip_evaluations e
            JOIN clips c ON c.id = e.clip_id
            LEFT JOIN candidates cand ON cand.id = c.candidate_id
            LEFT JOIN jobs j ON j.id = e.job_id
            LEFT JOIN videos v ON v.job_id = e.job_id
            {where}
            ORDER BY e.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["rejection_reasons"] = _parse_json_field(d.get("rejection_reasons"), [])
        d["config_snapshot"] = _parse_json_field(d.get("config_snapshot"), {})
        d["pipeline_snapshot"] = _parse_json_field(d.get("pipeline_snapshot"), {})
        result.append(d)
    return result


def add_missed_moment(job_id: str, video_id: str, start_s: float, end_s: float,
                      notes: str = "") -> str:
    mid = new_id()
    with db() as conn:
        conn.execute("""
            INSERT INTO missed_moments (id, job_id, video_id, start_s, end_s, notes, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (mid, job_id, video_id or "", start_s, end_s, notes, now()))
    return mid


def list_missed_moments(job_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM missed_moments WHERE job_id=? ORDER BY start_s ASC",
            (job_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_missed_moment(moment_id: str):
    with db() as conn:
        conn.execute("DELETE FROM missed_moments WHERE id=?", (moment_id,))


# ── YouTube upload session helpers ────────────────────────────────────────────

_YT_SESSION_ALLOWED_COLS = {
    "status", "session_url", "remote_video_id", "remote_process_status",
    "remote_privacy_status", "bytes_sent", "file_size", "file_path", "file_hash",
    "attempts", "last_attempt_at", "error_message", "error_code",
    "locked_at", "locked_by", "updated_at",
}


def create_yt_upload_session(
    pub_id: str, clip_id: str, channel_id: str, title: str,
    description: str, tags: list, is_for_kids: bool,
    file_path: str, file_hash: str, file_size: int,
    privacy_status: str = "private",
) -> str:
    sid = new_id()
    ts = now()
    with db() as conn:
        conn.execute("""
            INSERT INTO yt_upload_sessions
            (id, pub_id, clip_id, channel_id, title, description, tags, is_for_kids,
             file_path, file_hash, file_size, status, bytes_sent, attempts,
             privacy_status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',0,0,?,?,?)
        """, (
            sid, pub_id, clip_id, channel_id, title or "", description or "",
            json.dumps(tags or []), 1 if is_for_kids else 0,
            file_path, file_hash, file_size, privacy_status, ts, ts,
        ))
    return sid


def get_yt_upload_session_by_pub(pub_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM yt_upload_sessions WHERE pub_id=?", (pub_id,)
        ).fetchone()
    if row:
        r = dict(row)
        r.pop("session_url", None)  # Never return to callers
        return r
    return None


def get_yt_upload_session(session_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM yt_upload_sessions WHERE id=?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def update_yt_upload_session(session_id: str, **kwargs):
    allowed = {k: v for k, v in kwargs.items() if k in _YT_SESSION_ALLOWED_COLS}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    vals = list(allowed.values()) + [session_id]
    with db() as conn:
        conn.execute(f"UPDATE yt_upload_sessions SET {sets} WHERE id=?", vals)


def claim_yt_upload_session(worker_id: str) -> dict | None:
    """Atomically claim the next pending session. Returns full row (with session_url)."""
    threshold = datetime.utcnow() - timedelta(minutes=5)
    threshold_iso = threshold.isoformat()
    with db() as conn:
        row = conn.execute("""
            SELECT * FROM yt_upload_sessions
            WHERE status='pending'
              AND (locked_at IS NULL OR locked_at < ?)
              AND attempts < 3
            ORDER BY created_at ASC
            LIMIT 1
        """, (threshold_iso,)).fetchone()
        if not row:
            return None
        ts = now()
        conn.execute(
            "UPDATE yt_upload_sessions SET locked_at=?, locked_by=?, updated_at=? WHERE id=?",
            (ts, worker_id, ts, row["id"]),
        )
    return dict(row)


def list_stale_yt_sessions() -> list[dict]:
    threshold = datetime.utcnow() - timedelta(minutes=10)
    threshold_iso = threshold.isoformat()
    with db() as conn:
        rows = conn.execute("""
            SELECT * FROM yt_upload_sessions
            WHERE status='uploading' AND locked_at < ?
        """, (threshold_iso,)).fetchall()
    return [dict(r) for r in rows]


# ── YouTube OAuth state ────────────────────────────────────────────────────────

def save_yt_oauth_state(state: str, code_verifier: str):
    ts = now()
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO yt_oauth_state (state, code_verifier, created_at) VALUES (?,?,?)",
            (state, code_verifier, ts),
        )


def consume_yt_oauth_state(state: str) -> str | None:
    """Return code_verifier if state is valid (and delete it). One-time use."""
    with db() as conn:
        row = conn.execute(
            "SELECT code_verifier FROM yt_oauth_state WHERE state=?", (state,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM yt_oauth_state WHERE state=?", (state,))
            return row["code_verifier"]
    return None


# ── Clip row helper ───────────────────────────────────────────────────────────

def get_clip(clip_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM clips WHERE id=?", (clip_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Clip package helpers ──────────────────────────────────────────────────────

def create_package(name: str, description: str = "") -> str:
    pid = new_id()
    ts = now()
    with db() as conn:
        conn.execute(
            "INSERT INTO clip_packages (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
            (pid, name, description or "", ts, ts),
        )
    return pid


def list_packages() -> list[dict]:
    with db() as conn:
        rows = conn.execute("""
            SELECT p.*, COUNT(i.id) as item_count
            FROM clip_packages p
            LEFT JOIN clip_package_items i ON i.package_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_package(package_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM clip_packages WHERE id=?", (package_id,)).fetchone()
        if not row:
            return None
        items = conn.execute("""
            SELECT i.pub_id, i.added_at, p.title, p.platform, p.status
            FROM clip_package_items i
            LEFT JOIN publications p ON p.id = i.pub_id
            WHERE i.package_id=?
            ORDER BY i.added_at ASC
        """, (package_id,)).fetchall()
    r = dict(row)
    r["items"] = [dict(i) for i in items]
    return r


def update_package(package_id: str, **kwargs):
    allowed = {k: v for k, v in kwargs.items() if k in ("name", "description")}
    if not allowed:
        return
    allowed["updated_at"] = now()
    sets = ", ".join(f"{k}=?" for k in allowed)
    vals = list(allowed.values()) + [package_id]
    with db() as conn:
        conn.execute(f"UPDATE clip_packages SET {sets} WHERE id=?", vals)


def delete_package(package_id: str):
    with db() as conn:
        conn.execute("DELETE FROM clip_packages WHERE id=?", (package_id,))


def add_package_items(package_id: str, pub_ids: list) -> int:
    ts = now()
    added = 0
    with db() as conn:
        for pub_id in pub_ids:
            conn.execute(
                "INSERT OR IGNORE INTO clip_package_items (id, package_id, pub_id, added_at) VALUES (?,?,?,?)",
                (new_id(), package_id, pub_id, ts),
            )
            added += conn.execute("SELECT changes()").fetchone()[0]
    return added


def remove_package_items(package_id: str, pub_ids: list) -> int:
    removed = 0
    with db() as conn:
        for pub_id in pub_ids:
            conn.execute(
                "DELETE FROM clip_package_items WHERE package_id=? AND pub_id=?",
                (package_id, pub_id),
            )
            removed += conn.execute("SELECT changes()").fetchone()[0]
    return removed


# ── Upload batch helpers ──────────────────────────────────────────────────────

def create_upload_batch(name: str, channel_id: str, idempotency_key: str,
                        pub_session_pairs: list,
                        approved_privacy: str = "private") -> str:
    bid = new_id()
    ts = now()
    with db() as conn:
        conn.execute("""
            INSERT INTO upload_batches (id, name, channel_id, idempotency_key, paused,
                total_items, approved_privacy, created_at, updated_at)
            VALUES (?,?,?,?,0,?,?,?,?)
        """, (bid, name or "", channel_id or "", idempotency_key,
              len(pub_session_pairs), approved_privacy, ts, ts))
        for pub_id, session_id in pub_session_pairs:
            conn.execute("""
                INSERT OR IGNORE INTO upload_batch_items
                    (id, batch_id, pub_id, session_id, added_at, privacy_status)
                VALUES (?,?,?,?,?,?)
            """, (new_id(), bid, pub_id, session_id, ts, approved_privacy))
    return bid


def get_batch_by_idempotency(key: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM upload_batches WHERE idempotency_key=?", (key,)
        ).fetchone()
    return dict(row) if row else None


def get_upload_batch(batch_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM upload_batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            return None
        items = conn.execute("""
            SELECT i.pub_id, i.session_id, i.added_at,
                   s.status, s.bytes_sent, s.file_size, s.error_message,
                   s.remote_video_id, p.title, p.platform
            FROM upload_batch_items i
            LEFT JOIN yt_upload_sessions s ON s.id = i.session_id
            LEFT JOIN publications p ON p.id = i.pub_id
            WHERE i.batch_id=?
            ORDER BY i.added_at ASC
        """, (batch_id,)).fetchall()
    r = dict(row)
    r["items"] = [dict(i) for i in items]
    statuses = {i["status"] for i in r["items"] if i["status"]}
    if r.get("paused"):
        r["derived_status"] = "paused"
    elif not statuses:
        r["derived_status"] = "pending"
    elif statuses <= {"private", "needs_check", "cancelled"}:
        r["derived_status"] = "done"
    elif statuses & {"pending", "uploading", "processing", "paused"}:
        r["derived_status"] = "active"
    elif "error" in statuses:
        r["derived_status"] = "error"
    else:
        r["derived_status"] = "done"
    return r


def list_upload_batches(limit: int = 50) -> list[dict]:
    with db() as conn:
        rows = conn.execute("""
            SELECT b.*,
                   COUNT(i.id) as item_count,
                   SUM(CASE WHEN s.status IN ('private','needs_check') THEN 1 ELSE 0 END) as done_items,
                   SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) as error_items,
                   SUM(CASE WHEN s.status IN ('pending','uploading','processing') THEN 1 ELSE 0 END) as active_items
            FROM upload_batches b
            LEFT JOIN upload_batch_items i ON i.batch_id = b.id
            LEFT JOIN yt_upload_sessions s ON s.id = i.session_id
            GROUP BY b.id
            ORDER BY b.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    result = []
    for row in rows:
        r = dict(row)
        if r.get("paused"):
            r["derived_status"] = "paused"
        elif r.get("active_items", 0) > 0:
            r["derived_status"] = "active"
        elif r.get("error_items", 0) > 0:
            r["derived_status"] = "error"
        else:
            r["derived_status"] = "done"
        result.append(r)
    return result


def pause_upload_batch(batch_id: str):
    ts = now()
    with db() as conn:
        conn.execute(
            "UPDATE upload_batches SET paused=1, updated_at=? WHERE id=?", (ts, batch_id)
        )
        conn.execute("""
            UPDATE yt_upload_sessions SET status='paused', updated_at=?
            WHERE id IN (SELECT session_id FROM upload_batch_items WHERE batch_id=?)
              AND status='pending'
        """, (ts, batch_id))


def resume_upload_batch(batch_id: str):
    ts = now()
    with db() as conn:
        conn.execute(
            "UPDATE upload_batches SET paused=0, updated_at=? WHERE id=?", (ts, batch_id)
        )
        conn.execute("""
            UPDATE yt_upload_sessions SET status='pending', updated_at=?
            WHERE id IN (SELECT session_id FROM upload_batch_items WHERE batch_id=?)
              AND status='paused'
        """, (ts, batch_id))


def retry_batch_errors(batch_id: str):
    ts = now()
    with db() as conn:
        conn.execute("""
            UPDATE yt_upload_sessions
            SET status='pending', attempts=0, error_message=NULL, error_code=NULL,
                locked_at=NULL, locked_by=NULL, updated_at=?
            WHERE id IN (SELECT session_id FROM upload_batch_items WHERE batch_id=?)
              AND status='error'
        """, (ts, batch_id))
        conn.execute("UPDATE upload_batches SET updated_at=? WHERE id=?", (ts, batch_id))
