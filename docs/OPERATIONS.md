# Operations Runbook

## Starting the server

```powershell
cd C:\Users\edupo\Desktop\ContentEngine
python server.py              # 2 workers (default)
python server.py 4            # 4 workers
python server.py --workers 4  # same
```

The server runs startup validation before launching:
- Verifies FFmpeg and FFprobe exist at configured paths
- Verifies output directory is writable
- Checks disk space (warns if < 1 GB free)
- Initializes DB schema (CREATE TABLE IF NOT EXISTS, ADD COLUMN IF MISSING)
- Runs zombie job cleanup (resets stuck jobs from last session)
- Starts worker pool, then uvicorn on port 8000

Dashboard: http://localhost:8000/dashboard  
API docs: http://localhost:8000/docs  
Health: http://localhost:8000/health  

## Stopping the server

Press `Ctrl+C` in the terminal running `server.py`.

Workers are daemon threads — they stop when the main process exits. A job currently being processed will be interrupted. On next startup, `_cleanup_zombie_jobs()` marks it FAILED and it can be retried.

## Changing worker count

Stop server → restart with different count:

```powershell
python server.py 4
```

## Checking system status

```
GET /health          — liveness + component checks (DB, FFmpeg, workers, disk)
GET /admin/status    — operational snapshot: queue, workers, errors, storage, perf
GET /workers/stats   — live worker state + queue depth
GET /performance/summary — average stage times across all jobs
```

## Monitoring jobs

```
GET /jobs                        — all jobs (paginated, filter by status)
GET /jobs/{id}                   — single job detail
GET /jobs/{id}/events            — SSE stream for live progress
GET /jobs/{id}/timing            — per-stage timing breakdown
```

## Retrying a failed job

From API:
```
POST /jobs/{id}/retry
```

From Dashboard: Library → Failed view → Retry button.

What happens:
1. Status reset to QUEUED in `jobs` table
2. Job re-queued in `job_queue`
3. Pipeline runs from scratch — transcript cache prevents re-transcription if same source file

## Cancelling a running job

Not available via API. To force-cancel:
1. Stop the server (Ctrl+C)
2. The job will be marked FAILED on next startup
3. Restart the server

## Workers

Workers are background threads — they don't have individual stop controls.  
To add/remove workers, restart the server with a different `--workers` value.

## Queue management

The job_queue is a SQLite table. To inspect:

```sql
SELECT status, COUNT(*) FROM job_queue GROUP BY status;
SELECT * FROM job_queue WHERE status='running';
```

To manually clear a stuck queue entry:
```sql
UPDATE job_queue SET status='failed', error='manually cleared' WHERE id='...';
```

## Storage management

### Storage locations (under `output/`):

| Path | Contents | Safe to delete? |
|------|---------|----------------|
| `uploads/` | Locally uploaded files | Only if videos are also deleted from DB |
| `downloads/` | yt-dlp downloads | Only if videos are also deleted from DB |
| `audio/` | Extracted 16kHz WAV | Yes — rebuilt on next run |
| `proxies/` | 360p 2fps analysis proxies | Yes — rebuilt on next run |
| `thumbnails/` | JPEG thumbnails | Yes — rebuilt on next view |
| `{creator}/{video}/` | Final rendered clips | Only via DELETE /clips or DELETE /videos |

### Check storage usage:

```
GET /admin/status    — storage breakdown by category
```

Or from PowerShell:
```powershell
Get-ChildItem -Recurse C:\Users\edupo\Desktop\ContentEngine\output | Measure-Object -Property Length -Sum
```

### Clean up audio cache (safe, rebuilds on demand):
```powershell
Remove-Item -Recurse -Force C:\Users\edupo\Desktop\ContentEngine\output\audio\*
```

### Clean up proxy cache (safe, rebuilds on demand):
```powershell
Remove-Item -Recurse -Force C:\Users\edupo\Desktop\ContentEngine\output\proxies\*
```

Note: After deleting proxies, update the DB so the next run regenerates them:
```sql
UPDATE videos SET proxy_path = NULL;
```

### Orphan file detection:

```
GET /admin/orphans   — clips with missing files, videos with missing source
```

## Database maintenance

### Backup:
```powershell
Copy-Item C:\Users\edupo\Desktop\ContentEngine\db\engine.sqlite `
          C:\Users\edupo\Desktop\ContentEngine\db\engine_backup_$(Get-Date -Format 'yyyyMMdd').sqlite
```

### Inspect DB size:
```powershell
(Get-Item C:\Users\edupo\Desktop\ContentEngine\db\engine.sqlite).Length / 1MB
```

### Vacuum (reclaim space after deletions):
```sql
VACUUM;
```
Run this while the server is stopped, directly via SQLite CLI.

## Logs

Logs go to stdout/stderr (configured in `server.py`):

```
HH:MM:SS INFO  pipeline_worker — Worker worker-abc123 started
HH:MM:SS INFO  pipeline_worker — Job abc12345 completed — 3 clips
HH:MM:SS ERROR pipeline_worker — Job abc12345 failed: ...
```

To capture to file:
```powershell
python server.py 2>&1 | Tee-Object -FilePath logs\server.log
```

## Recovery scenarios

### Server crashed mid-job
1. Restart: `python server.py`
2. Zombie cleanup sets the interrupted job to FAILED
3. Dashboard shows the job as FAILED with error "Server restarted — job was interrupted"
4. Use Retry button or `POST /jobs/{id}/retry`
5. Transcript is cached — retry is fast (skip re-transcription)

### DB corruption
1. Stop server
2. Restore from backup
3. Restart

### Disk full
1. Stop server
2. Delete audio/proxy/thumbnail caches (see Storage section)
3. Delete old/unwanted clips via Dashboard or `DELETE /clips/{id}` API
4. Restart server

### FFmpeg missing after update
1. Update `FFMPEG_PATH` and `FFPROBE_PATH` in `engine/config.py`
2. Restart server

## Debugging

### Check a specific job:
```
GET /jobs/{id}           — status, error message
GET /jobs/{id}/timing    — which stage was slow
GET /jobs/{id}/analysis  — candidate scores
```

### Check worker state:
```
GET /workers/stats
```

### Check a clip file exists:
```
GET /admin/orphans
```

### View pipeline timing across all jobs:
```
GET /performance/summary
```

### Inspect job_queue directly (PowerShell):
```powershell
& 'C:\...\sqlite3.exe' C:\Users\edupo\Desktop\ContentEngine\db\engine.sqlite `
  "SELECT id, status, attempts, error FROM job_queue ORDER BY created_at DESC LIMIT 10;"
```

## Health check

```
GET /health
```

Returns:
```json
{
  "status": "ok",
  "mode": "REVIEW",
  "version": "1.0.0",
  "checks": {
    "database": "ok",
    "ffmpeg": "ok",
    "ffprobe": "ok",
    "workers": "2/2 alive",
    "disk_free_gb": "42.3"
  }
}
```

`status: "degraded"` means database is unreachable — server cannot process jobs.

## Performance tuning

### Increase workers (more parallel jobs):
```powershell
python server.py 4
```

### Enable GPU transcription (if NVIDIA GPU available):
In `engine/transcription.py`, change:
```python
_WHISPER_MODEL = WhisperModel(CONFIG.whisper_model, device="cpu", compute_type="int8")
```
to:
```python
_WHISPER_MODEL = WhisperModel(CONFIG.whisper_model, device="cuda", compute_type="float16")
```

### Upgrade Whisper model (better quality, slower):
In `engine/config.py`, change `whisper_model: str = "base"` to `"small"`, `"medium"`, or `"large-v3"`.
