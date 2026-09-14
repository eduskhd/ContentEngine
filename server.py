#!/usr/bin/env python3
"""
ContentEngine Server
Initializes the database, starts the worker pool, and serves the REST API.

Usage:
    python server.py              # 2 workers (default)
    python server.py 4            # 4 workers
    python server.py --workers 4  # same
"""
import sys, io, logging

# Windows: force UTF-8 on stdout/stderr before any Rich Console objects are created.
# Without this, pipeline.py's Console() captures cp1252 stdout and crashes on box-drawing
# characters (U+2500 ─) that are not in cp1252, causing jobs to be marked FAILED.
if hasattr(sys.stdout, "buffer") and getattr(sys.stdout, "encoding", "").lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer") and getattr(sys.stderr, "encoding", "").lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

import uvicorn

from engine.database import init_db
from engine.config import CONFIG
from workers.pipeline_worker import WorkerPool
import api.main as api_module


def _parse_workers(argv: list[str]) -> int:
    for i, arg in enumerate(argv):
        if arg == "--workers" and i + 1 < len(argv):
            return int(argv[i + 1])
        try:
            return int(arg)
        except ValueError:
            pass
    return 2


def _validate_environment():
    """Fail fast with a clear message if critical dependencies are missing."""
    import shutil as _shutil
    from pathlib import Path as _Path
    errors = []

    # FFmpeg / FFprobe
    if not _Path(CONFIG.ffmpeg_path).exists():
        errors.append(f"ffmpeg not found at: {CONFIG.ffmpeg_path}")
    if not _Path(CONFIG.ffprobe_path).exists():
        errors.append(f"ffprobe not found at: {CONFIG.ffprobe_path}")

    # Output directory writable
    try:
        _Path(CONFIG.output_dir).mkdir(parents=True, exist_ok=True)
        test_file = _Path(CONFIG.output_dir) / ".write_test"
        test_file.touch(); test_file.unlink()
    except Exception as exc:
        errors.append(f"Output directory not writable ({CONFIG.output_dir}): {exc}")

    # DB directory writable
    try:
        _Path(CONFIG.db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        errors.append(f"DB directory not writable ({CONFIG.db_path}): {exc}")

    # Disk space
    try:
        free_gb = _shutil.disk_usage(CONFIG.output_dir).free / (1024 ** 3)
        if free_gb < 1.0:
            errors.append(f"CRITICAL: only {free_gb:.1f} GB free on output disk")
    except Exception:
        pass

    if errors:
        print("\n[FATAL] Environment validation failed:")
        for e in errors:
            print(f"  ✗ {e}")
        print("\nFix the above issues before starting the server.")
        sys.exit(1)


def main():
    num_workers = _parse_workers(sys.argv[1:])

    print("=" * 60)
    print("  AI SHORT-FORM CONTENT ENGINE")
    print(f"  Mode   : {CONFIG.mode}")
    print(f"  Workers: {num_workers}")
    print(f"  DB     : {CONFIG.db_path}")
    print(f"  Output : {CONFIG.output_dir}")
    print("=" * 60)

    _validate_environment()

    # 1. Initialise DB schema
    print("\n[boot] Initialising database...")
    init_db()

    # 2. Create worker pool — share the API's _jobs dict so workers update live status
    print(f"[boot] Creating {num_workers} pipeline worker(s)...")
    pool = WorkerPool(num_workers=num_workers, jobs_dict=api_module._jobs)

    # 3. Inject pool into API module before uvicorn starts
    api_module.pool = pool

    print("[boot] API server starting on http://localhost:8000")
    print("[boot] Dashboard: http://localhost:8000/dashboard")
    print("[boot] API docs:  http://localhost:8000/docs")
    print()

    # 4. Launch FastAPI via uvicorn
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
