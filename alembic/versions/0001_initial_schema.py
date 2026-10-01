"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
        metadata TEXT DEFAULT '{}',
        creator_id TEXT,
        error_category TEXT,
        pipeline_snapshot TEXT
    )
    """)
    op.execute("""
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
        creator_slug TEXT,
        video_slug TEXT,
        source_url TEXT,
        source_platform TEXT,
        source_title TEXT,
        creator_id TEXT,
        thumbnail_path TEXT,
        words_json TEXT,
        proxy_path TEXT,
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    )
    """)
    op.execute("""
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
        emotion_score REAL DEFAULT 0.0,
        retention_score REAL DEFAULT 0.0,
        importance_score REAL DEFAULT 0.0,
        hook_time REAL DEFAULT 0.0,
        virality_reasons TEXT DEFAULT '[]',
        smart_start REAL,
        smart_end REAL,
        series_id TEXT,
        series_part INTEGER DEFAULT 0,
        FOREIGN KEY (job_id) REFERENCES jobs(id),
        FOREIGN KEY (video_id) REFERENCES videos(id)
    )
    """)
    op.execute("""
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
        review_notes TEXT,
        caption_data TEXT,
        caption_settings TEXT,
        FOREIGN KEY (job_id) REFERENCES jobs(id),
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS publish_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clip_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        post_id TEXT,
        url TEXT,
        published_at TEXT NOT NULL,
        FOREIGN KEY (clip_id) REFERENCES clips(id)
    )
    """)
    op.execute("""
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
        raw_json TEXT,
        predicted_virality_score REAL,
        actual_vs_predicted_delta REAL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS performance_benchmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT,
        content_type TEXT,
        percentile_25 REAL,
        percentile_50 REAL,
        percentile_75 REAL,
        percentile_90 REAL,
        updated_at TEXT
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
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
        channel_name TEXT,
        FOREIGN KEY (creator_id) REFERENCES creators(id)
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS publication_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        publication_id TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_timings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        start_ts REAL,
        end_ts REAL,
        duration_s REAL,
        status TEXT DEFAULT 'ok',
        meta TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        llm_tokens_used INTEGER DEFAULT 0,
        llm_cost_usd REAL DEFAULT 0.0
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS collections (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        color TEXT DEFAULT '#3b82f6',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS collection_items (
        id TEXT PRIMARY KEY,
        collection_id TEXT NOT NULL,
        item_type TEXT NOT NULL,
        item_id TEXT NOT NULL,
        added_at TEXT NOT NULL,
        FOREIGN KEY (collection_id) REFERENCES collections(id),
        UNIQUE(collection_id, item_type, item_id)
    )
    """)
    op.execute("""
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
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS missed_moments (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        video_id TEXT DEFAULT '',
        start_s REAL NOT NULL,
        end_s REAL NOT NULL,
        notes TEXT DEFAULT '',
        generated_clip_id TEXT,
        created_at TEXT
    )
    """)
    op.execute("""
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
        privacy_status TEXT DEFAULT 'private',
        series_id TEXT,
        series_part INTEGER DEFAULT 0,
        FOREIGN KEY (pub_id) REFERENCES publications(id),
        FOREIGN KEY (clip_id) REFERENCES clips(id),
        UNIQUE (pub_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS yt_oauth_state (
        state TEXT PRIMARY KEY,
        code_verifier TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS clip_packages (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS clip_package_items (
        id TEXT PRIMARY KEY,
        package_id TEXT NOT NULL REFERENCES clip_packages(id) ON DELETE CASCADE,
        pub_id TEXT NOT NULL,
        added_at TEXT NOT NULL,
        UNIQUE(package_id, pub_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS upload_batches (
        id TEXT PRIMARY KEY,
        name TEXT,
        channel_id TEXT,
        idempotency_key TEXT UNIQUE,
        paused INTEGER DEFAULT 0,
        total_items INTEGER DEFAULT 0,
        approved_privacy TEXT DEFAULT 'private',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS upload_batch_items (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES upload_batches(id) ON DELETE CASCADE,
        pub_id TEXT NOT NULL,
        session_id TEXT,
        privacy_status TEXT DEFAULT 'private',
        added_at TEXT NOT NULL,
        UNIQUE(batch_id, pub_id)
    )
    """)

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_candidates_job_id   ON candidates(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_candidates_video_id ON candidates(video_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_clips_job_id        ON clips(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_clips_candidate_id  ON clips(candidate_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status         ON jobs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at     ON jobs(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_videos_path         ON videos(path)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_videos_job_id       ON videos(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_videos_creator_id   ON videos(creator_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pt_job_id           ON pipeline_timings(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pubs_clip_id        ON publications(clip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pubs_status         ON publications(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pubs_creator_id     ON publications(creator_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_prepub_clip_id      ON prepublish_decisions(clip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_coll_items_coll     ON collection_items(collection_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_coll_items_item     ON collection_items(item_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_clip_evals_clip_id  ON clip_evaluations(clip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_clip_evals_job_id   ON clip_evaluations(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_missed_job_id       ON missed_moments(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_yt_sessions_status  ON yt_upload_sessions(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_yt_sessions_pub_id  ON yt_upload_sessions(pub_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pkg_items_pkg       ON clip_package_items(package_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_batch_items_batch   ON upload_batch_items(batch_id)")
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_jq_status
        ON job_queue(status, priority DESC, created_at ASC)
    """)


def downgrade() -> None:
    tables = [
        "upload_batch_items", "upload_batches", "clip_package_items", "clip_packages",
        "yt_oauth_state", "yt_upload_sessions", "missed_moments", "clip_evaluations",
        "collection_items", "collections", "pipeline_timings", "publication_audit_log",
        "publication_metrics", "social_accounts", "publications", "creators",
        "clip_series", "autopsy_reports", "weight_history", "job_queue",
        "performance_benchmarks", "post_metrics", "publish_log", "prepublish_decisions",
        "skill_runs", "clips", "candidates", "videos", "jobs",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t}")
