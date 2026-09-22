"""
Cleanup ghost data from fake test jobs.

Ghost data = clips/candidates/jobs whose source is '/fake/path.mp4'
or whose candidate has no matching video in the videos table.

This script:
  --dry-run  (default) : show what would be deleted, no changes
  --apply             : actually archive/delete the records
  --restore           : restore archived records

Archived records are kept in separate _archive tables for reversibility.
Run 'python cleanup_ghost_data.py' first to review, then '--apply' to clean.
"""
import sqlite3, argparse, datetime, shutil, os, sys

DB_PATH = "db/engine.sqlite"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply cleanup (default: dry-run)")
    parser.add_argument("--restore", action="store_true", help="Restore archived records")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}"); sys.exit(1)

    # Backup before any write
    if args.apply or args.restore:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bk = f"{DB_PATH}.bak_{ts}"
        shutil.copy2(DB_PATH, bk)
        print(f"Backup created: {bk}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if args.restore:
        restore(conn)
        conn.commit(); conn.close()
        return

    identify_and_clean(conn, dry_run=not args.apply)
    if not args.apply:
        conn.close()
        return
    conn.commit()
    conn.close()
    print("\nCleanup applied. Run --restore to undo.")


def identify_and_clean(conn, dry_run):
    mode = "DRY RUN" if dry_run else "APPLYING"
    print(f"\n=== Ghost Data Cleanup [{mode}] ===\n")

    # ── Ensure archive tables exist ──────────────────────────────────────────
    conn.execute("""CREATE TABLE IF NOT EXISTS _archived_jobs AS SELECT * FROM jobs WHERE 0""")
    conn.execute("""CREATE TABLE IF NOT EXISTS _archived_clips AS SELECT * FROM clips WHERE 0""")
    conn.execute("""CREATE TABLE IF NOT EXISTS _archived_candidates AS SELECT * FROM candidates WHERE 0""")
    conn.execute("CREATE TABLE IF NOT EXISTS _archive_meta (archived_at TEXT, reason TEXT, job_ids TEXT, clip_ids TEXT, candidate_ids TEXT)")

    # ── Find fake jobs ────────────────────────────────────────────────────────
    fake_jobs = conn.execute("""
        SELECT id, source_path, status, created_at FROM jobs
        WHERE source_path LIKE '%/fake/path%' OR source_path LIKE '%\\fake\\path%'
           OR source_path = '/fake/path.mp4'
        ORDER BY created_at
    """).fetchall()

    print(f"Fake jobs (source=/fake/path.mp4): {len(fake_jobs)}")
    for j in fake_jobs[:5]:
        print(f"  job={j['id'][:8]} status={j['status']} created={str(j['created_at'])[:10]}")
    if len(fake_jobs) > 5:
        print(f"  ... and {len(fake_jobs)-5} more")

    fake_job_ids = [j['id'] for j in fake_jobs]

    # ── Find ghost clips (no matching video, or no candidate) ────────────────
    ghost_clips_no_vid = conn.execute("""
        SELECT cl.id, cl.job_id, ca.video_id FROM clips cl
        LEFT JOIN candidates ca ON cl.candidate_id = ca.id
        WHERE cl.candidate_id IS NULL
           OR ca.id IS NULL
           OR ca.video_id IS NULL
           OR ca.video_id NOT IN (SELECT id FROM videos)
    """).fetchall()
    print(f"\nGhost clips (no matching video): {len(ghost_clips_no_vid)}")
    for c in ghost_clips_no_vid[:5]:
        print(f"  clip={c['id'][:8]} job={str(c['job_id'] or '')[:8]} vid={str(c['video_id'] or 'NULL')[:8]}")
    if len(ghost_clips_no_vid) > 5:
        print(f"  ... and {len(ghost_clips_no_vid)-5} more")

    ghost_clip_ids = [c['id'] for c in ghost_clips_no_vid]

    # ── Find orphaned candidates ─────────────────────────────────────────────
    ghost_cands = conn.execute("""
        SELECT id, video_id FROM candidates
        WHERE video_id IS NULL
           OR video_id NOT IN (SELECT id FROM videos)
    """).fetchall()
    ghost_cand_ids = [c['id'] for c in ghost_cands]
    print(f"\nOrphaned candidates (no matching video): {len(ghost_cand_ids)}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\nSummary:")
    print(f"  Jobs to archive:       {len(fake_job_ids)}")
    print(f"  Clips to archive:      {len(ghost_clip_ids)}")
    print(f"  Candidates to archive: {len(ghost_cand_ids)}")
    print(f"  Real videos untouched: ", conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
    print(f"  Real clips kept:       ", conn.execute("""
        SELECT COUNT(*) FROM clips cl
        JOIN candidates ca ON cl.candidate_id = ca.id
        WHERE ca.video_id IN (SELECT id FROM videos)
    """).fetchone()[0])

    if dry_run:
        print("\nDry run complete. Run with --apply to execute cleanup.")
        return

    # ── Archive and delete ────────────────────────────────────────────────────
    if fake_job_ids:
        ph = ','.join('?'*len(fake_job_ids))
        conn.execute(f"INSERT INTO _archived_jobs SELECT * FROM jobs WHERE id IN ({ph})", fake_job_ids)
        conn.execute(f"DELETE FROM jobs WHERE id IN ({ph})", fake_job_ids)
        print(f"\nArchived {len(fake_job_ids)} fake jobs")

    if ghost_clip_ids:
        ph = ','.join('?'*len(ghost_clip_ids))
        conn.execute(f"INSERT INTO _archived_clips SELECT * FROM clips WHERE id IN ({ph})", ghost_clip_ids)
        conn.execute(f"DELETE FROM clips WHERE id IN ({ph})", ghost_clip_ids)
        print(f"Archived {len(ghost_clip_ids)} ghost clips")

    if ghost_cand_ids:
        ph = ','.join('?'*len(ghost_cand_ids))
        conn.execute(f"INSERT INTO _archived_candidates SELECT * FROM candidates WHERE id IN ({ph})", ghost_cand_ids)
        conn.execute(f"DELETE FROM candidates WHERE id IN ({ph})", ghost_cand_ids)
        print(f"Archived {len(ghost_cand_ids)} orphaned candidates")

    conn.execute("INSERT INTO _archive_meta VALUES (?,?,?,?,?)", [
        datetime.datetime.now().isoformat(), "ghost_data_cleanup",
        ','.join(fake_job_ids[:20]),
        ','.join(ghost_clip_ids[:20]),
        ','.join(ghost_cand_ids[:20]),
    ])
    print("\nDone. Use --restore to undo.")


def restore(conn):
    print("\n=== Restoring Archived Records ===\n")

    for tbl, arch in [('jobs', '_archived_jobs'), ('clips', '_archived_clips'), ('candidates', '_archived_candidates')]:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {arch}").fetchone()[0]
            if n:
                conn.execute(f"INSERT OR IGNORE INTO {tbl} SELECT * FROM {arch}")
                conn.execute(f"DELETE FROM {arch}")
                print(f"Restored {n} records to {tbl}")
            else:
                print(f"No archived records in {arch}")
        except Exception as e:
            print(f"  Warning: {arch}: {e}")

    print("\nRestore complete.")


if __name__ == "__main__":
    main()
