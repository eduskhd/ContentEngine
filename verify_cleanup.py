import sqlite3
c = sqlite3.connect('db/engine.sqlite')
c.row_factory = sqlite3.Row
print('=== After cleanup ===')
print('Jobs:', c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0])
print('Videos:', c.execute('SELECT COUNT(*) FROM videos').fetchone()[0])
print('Clips:', c.execute('SELECT COUNT(*) FROM clips').fetchone()[0])
print('Candidates:', c.execute('SELECT COUNT(*) FROM candidates').fetchone()[0])
print()
print('Archived:')
print('  _archived_jobs:', c.execute('SELECT COUNT(*) FROM _archived_jobs').fetchone()[0])
print('  _archived_clips:', c.execute('SELECT COUNT(*) FROM _archived_clips').fetchone()[0])
print('  _archived_candidates:', c.execute('SELECT COUNT(*) FROM _archived_candidates').fetchone()[0])
print()
print('Failed jobs remaining:', c.execute("SELECT COUNT(*) FROM jobs WHERE status='FAILED'").fetchone()[0])
print('Ghost clips remaining:', c.execute("""
    SELECT COUNT(*) FROM clips cl
    LEFT JOIN candidates ca ON cl.candidate_id = ca.id
    WHERE ca.video_id IS NULL OR ca.video_id NOT IN (SELECT id FROM videos)
""").fetchone()[0])
print('Review pending (real):', c.execute("""
    SELECT COUNT(*) FROM clips cl
    JOIN candidates ca ON cl.candidate_id = ca.id
    JOIN videos v ON v.id = ca.video_id
    WHERE cl.prepublish_decision IN ('REVIEW','PENDING')
""").fetchone()[0])
c.close()
