"""Background pipeline workers — thread pool polling the SQLite job queue."""
import threading, time, uuid, logging
from engine.pipeline import process_video
from workers.job_queue import JobQueue

logger = logging.getLogger("pipeline_worker")


class PipelineWorker(threading.Thread):
    def __init__(self, worker_id: str = None, queue: JobQueue = None,
                 jobs_dict: dict = None, poll_interval: float = 2.0):
        super().__init__(daemon=True)
        self.worker_id  = worker_id or f"worker-{str(uuid.uuid4())[:8]}"
        self.queue      = queue or JobQueue()
        self.jobs_dict  = jobs_dict  # reference to api._jobs for live status
        self.poll_interval = poll_interval
        self._stop      = threading.Event()
        self.active_job: str | None = None

    def run(self):
        logger.info("Worker %s started", self.worker_id)
        while not self._stop.is_set():
            job = self.queue.dequeue(self.worker_id)
            if job:
                self._process(job)
            else:
                time.sleep(self.poll_interval)

    def _set(self, job_id: str, **kwargs):
        """Update the in-memory _jobs dict if available."""
        if self.jobs_dict is not None and job_id in self.jobs_dict:
            self.jobs_dict[job_id].update(kwargs)

    def _process(self, job: dict):
        self.active_job = job["id"]
        p   = job["payload"]
        jid = p["job_id"]          # unified API + DB job ID

        logger.info("Worker %s → job %s", self.worker_id, jid[:8])
        self._set(jid, status="running")

        try:
            result = process_video(
                source           = p["source"],
                number_of_clips  = p.get("clips", 3),
                target_platforms = p.get("platforms", ["tiktok", "instagram"]),
                creator          = p.get("creator", "unknown"),
                job_id           = jid,
            )
            self._set(jid, status="completed", result=result,
                      creator_slug=result.get("creator_slug"),
                      video_slug=result.get("video_slug"),
                      source_title=result.get("source_title"),
                      source_platform=result.get("source_platform"))
            self.queue.complete(job["id"], {"job_id": jid, "stats": result.get("stats")})
            logger.info("Job %s completed — %d clips", jid[:8],
                        result.get("stats", {}).get("clips_generated", 0))
        except Exception as e:
            self._set(jid, status="failed", error=str(e))
            self.queue.fail(job["id"], str(e))
            # Always ensure the jobs table reflects FAILED — process_video may have
            # raised before the pipeline's own except block ran (e.g., duplicate INSERT).
            try:
                from engine.database import update_job
                update_job(jid, status="FAILED", error=str(e))
            except Exception:
                pass
            logger.error("Job %s failed: %s", jid[:8], e, exc_info=True)
        finally:
            self.active_job = None

    def stop(self):
        self._stop.set()


class WorkerPool:
    def __init__(self, num_workers: int = 2, jobs_dict: dict = None):
        self.queue   = JobQueue()
        self._jobs   = jobs_dict   # kept for late injection (server.py wires this after)
        self.workers = [
            PipelineWorker(queue=self.queue, jobs_dict=jobs_dict)
            for _ in range(num_workers)
        ]

    def set_jobs_dict(self, jobs_dict: dict):
        """Wire the live _jobs reference after construction (called by server.py)."""
        self._jobs = jobs_dict
        for w in self.workers:
            w.jobs_dict = jobs_dict

    def start(self):
        self._cleanup_zombie_jobs()
        for w in self.workers:
            w.start()
        return self

    def _cleanup_zombie_jobs(self):
        """On restart: mark interrupted jobs as FAILED and reset stuck queue entries."""
        import sqlite3
        from datetime import datetime
        from engine.config import CONFIG
        try:
            conn = sqlite3.connect(CONFIG.db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            ts = datetime.utcnow().isoformat()

            # 1. Mark jobs table rows that were mid-pipeline as FAILED
            cur = conn.execute(
                "UPDATE jobs SET status='FAILED', "
                "error='Server restarted — job was interrupted', updated_at=? "
                "WHERE status NOT IN ('COMPLETED','FAILED','QUEUED')",
                [ts],
            )
            if cur.rowcount:
                logger.info("Cleaned up %d zombie job(s) from previous session", cur.rowcount)

            # 2. Reset job_queue rows stuck in 'running' so they can be retried.
            #    If max_attempts not yet exhausted → back to 'queued'.
            #    If exhausted → mark 'failed' so they don't loop forever.
            cur2 = conn.execute(
                "UPDATE job_queue SET status='queued', worker_id=NULL "
                "WHERE status='running' AND attempts < max_attempts",
                [],
            )
            if cur2.rowcount:
                logger.info("Reset %d stuck queue entry(s) back to queued", cur2.rowcount)

            cur3 = conn.execute(
                "UPDATE job_queue SET status='failed', "
                "error='Server restarted — max attempts reached' "
                "WHERE status='running' AND attempts >= max_attempts",
                [],
            )
            if cur3.rowcount:
                logger.info("Exhausted %d queue entry(s) that hit max_attempts", cur3.rowcount)

            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Could not cleanup zombie jobs: %s", exc)

    def stop(self):
        for w in self.workers:
            w.stop()

    def submit(self, job_id: str, source: str, clips: int = 3,
               platforms: list = None, mode: str = "REVIEW",
               creator: str = "unknown", priority: int = 0) -> str:
        """Enqueue a job. Returns the queue task ID (not the pipeline job_id)."""
        return self.queue.enqueue({
            "job_id":    job_id,
            "source":    source,
            "clips":     clips,
            "platforms": platforms or ["tiktok", "instagram"],
            "mode":      mode,
            "creator":   creator,
        }, priority=priority)

    def stats(self) -> dict:
        return {
            "queue":   self.queue.stats(),
            "workers": [
                {"id": w.worker_id, "active_job": w.active_job, "alive": w.is_alive()}
                for w in self.workers
            ],
        }
