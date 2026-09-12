"""SQLite-backed job queue. Interface is Redis-compatible for future migration."""
import sqlite3, json, uuid
from datetime import datetime
from pathlib import Path
from engine.config import CONFIG


class JobQueue:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or CONFIG.db_path
        self._ensure_table()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_table(self):
        with self._conn() as conn:
            conn.executescript("""
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
                CREATE INDEX IF NOT EXISTS idx_jq_status
                    ON job_queue(status, priority DESC, created_at ASC);
            """)

    def enqueue(self, payload: dict, priority: int = 0) -> str:
        job_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO job_queue (id, payload, priority, created_at) VALUES (?,?,?,?)",
                [job_id, json.dumps(payload), priority, datetime.utcnow().isoformat()],
            )
        return job_id

    def dequeue(self, worker_id: str) -> dict | None:
        # Atomic SELECT + UPDATE using RETURNING — only one worker can claim a job.
        # The subquery-in-UPDATE pattern is the SQLite-idiomatic "skip locked" equivalent.
        conn = self._conn()
        try:
            row = conn.execute("""
                UPDATE job_queue
                SET status='running', started_at=?, worker_id=?, attempts=attempts+1
                WHERE id=(
                    SELECT id FROM job_queue
                    WHERE status='queued' AND attempts < max_attempts
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                )
                RETURNING id, payload
            """, [datetime.utcnow().isoformat(), worker_id]).fetchone()
            conn.commit()
            if not row:
                return None
            return {"id": row[0], "payload": json.loads(row[1])}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete(self, job_id: str, result: dict):
        with self._conn() as conn:
            conn.execute(
                "UPDATE job_queue SET status='completed', completed_at=?, result=? WHERE id=?",
                [datetime.utcnow().isoformat(), json.dumps(result), job_id],
            )

    def fail(self, job_id: str, error: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE job_queue SET status='failed', error=?, completed_at=? WHERE id=?",
                [error, datetime.utcnow().isoformat(), job_id],
            )

    def status(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM job_queue WHERE id=?", [job_id]).fetchone()
            return dict(row) if row else None

    def stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as n FROM job_queue GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}
