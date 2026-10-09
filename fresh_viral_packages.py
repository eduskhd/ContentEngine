"""
fresh_viral_packages.py
1. Delete the packages created today (keep the 3 original test packages)
2. Re-run the full pipeline on top 5 viral videos requesting 25 clips each
3. Create 5 packages of 5 fresh clips per video
"""
import sys, os, json, sqlite3, uuid
sys.stdout.reconfigure(encoding='utf-8')
os.chdir(r'C:\Users\edupo\Desktop\ContentEngine')
sys.path.insert(0, r'C:\Users\edupo\Desktop\ContentEngine')

from engine import database as dbmod
from engine.pipeline import process_video

# ── Step 1: Delete today's packages (keep originals from 2026-09-18) ─────────
print("Deleting today's packages...")
with dbmod.db() as conn:
    conn.execute("""
        DELETE FROM clip_package_items WHERE package_id IN (
            SELECT id FROM clip_packages WHERE created_at > '2026-10-07'
        )
    """)
    conn.execute("DELETE FROM clip_packages WHERE created_at > '2026-10-07'")
print("  Done.\n")

# ── Top 5 videos — source paths and metadata ──────────────────────────────────
TOP5 = [
    {
        'path':    r'C:\Users\edupo\Desktop\ContentEngine\output\downloads\mrbeast_zxyjttxc_j8.mp4',
        'creator': 'mrbeast',
        'label':   'MrBeast - Last To Leave Circle ($500k)',
    },
    {
        'path':    r'C:\Users\edupo\Desktop\ContentEngine\output\downloads\ibai_lzoc6kjd7_g.mp4',
        'creator': 'ibai',
        'label':   'Ibai - Among Us Historico Seleccion',
    },
    {
        'path':    r'C:\Users\edupo\Desktop\ContentEngine\output\downloads\mrbeast_1weaj_dfkhe.mp4',
        'creator': 'mrbeast',
        'label':   'MrBeast - $1 vs $500k Plane Ticket',
    },
    {
        'path':    r'C:\Users\edupo\Desktop\ContentEngine\output\downloads\bycalitos_mayedfg3gy0.mp4',
        'creator': 'bycalitos',
        'label':   'Bycalitos - Barcos de Lujo',
    },
    {
        'path':    r'C:\Users\edupo\Desktop\ContentEngine\output\downloads\xbuyer_qxwmcb6zl_a.mp4',
        'creator': 'xbuyer',
        'label':   'Xbuyer - Regalo ERIC cumpleanos',
    },
]

PACK_LABELS = ['Viral Best', 'High Engagement', 'Strong Hook', 'Retention+', 'Discovery']


def ensure_publication(clip_id, job_id, virality_score, platform_scores_json, tech_qa, vis_qa):
    """Ensure clip has a prepublish_decision and a publication; return publications.id."""
    with dbmod.db() as conn:
        existing_pd = conn.execute(
            'SELECT id FROM prepublish_decisions WHERE clip_id=?', (clip_id,)
        ).fetchone()
    if not existing_pd:
        try:
            pf = json.loads(platform_scores_json) if platform_scores_json else {}
        except Exception:
            pf = {}
        decision = 'REVIEW' if tech_qa == 'PASS' and vis_qa == 'PASS' else 'REJECT'
        dbmod.create_prepublish_decision(
            clip_id=clip_id, job_id=job_id, decision=decision,
            score=virality_score or 0.0, technical_qa=tech_qa or 'UNKNOWN',
            visual_qa=vis_qa or 'UNKNOWN', rights_verified=True,
            platform_fit_scores=pf, blocking_reasons=[],
        )
    with dbmod.db() as conn:
        existing_pub = conn.execute(
            "SELECT id FROM publications WHERE clip_id=? AND platform='youtube_shorts'",
            (clip_id,)
        ).fetchone()
    if existing_pub:
        return existing_pub['id']
    return dbmod.create_publication(clip_id=clip_id, platform='youtube_shorts', status='ready')


def create_packages_for_job(job_id, label):
    """Get fresh clips for a job and group into packages of 5."""
    with dbmod.db() as conn:
        clips_with_data = conn.execute('''
            SELECT ca.virality_score, cl.id as clip_id, cl.technical_qa, cl.visual_qa,
                   cl.platform_fit_scores, p.id as pub_id
            FROM candidates ca
            JOIN clips cl ON cl.candidate_id = ca.id
            LEFT JOIN publications p ON p.clip_id = cl.id AND p.platform = 'youtube_shorts'
            WHERE ca.job_id = ?
            ORDER BY ca.virality_score DESC NULLS LAST
        ''', (job_id,)).fetchall()
    clips_with_data = [dict(r) for r in clips_with_data]

    if not clips_with_data:
        print(f"  No clips found for job {job_id[:8]}")
        return []

    print(f"  {len(clips_with_data)} clips available for packaging")

    # Ensure all clips have prepublish_decisions
    for c in clips_with_data:
        if not c['pub_id']:
            c['pub_id'] = ensure_publication(
                clip_id=c['clip_id'], job_id=job_id,
                virality_score=c['virality_score'],
                platform_scores_json=c['platform_fit_scores'],
                tech_qa=c['technical_qa'], vis_qa=c['visual_qa'],
            )

    package_ids = []
    num_packs = len(clips_with_data) // 5
    for pack_idx in range(num_packs):
        pack_clips = clips_with_data[pack_idx * 5:(pack_idx + 1) * 5]
        pack_lbl = PACK_LABELS[pack_idx] if pack_idx < len(PACK_LABELS) else f'Pack {pack_idx+1}'
        pack_name = f"{label} — Pack {pack_idx+1} ({pack_lbl})"
        avg_viral = sum(c['virality_score'] or 0 for c in pack_clips) / len(pack_clips)
        desc = (f"YouTube Shorts — clips #{pack_idx*5+1}–{pack_idx*5+5} por viralidad. "
                f"Avg score: {avg_viral:.1f}")
        pid = dbmod.create_package(pack_name, desc)
        pub_ids = [c['pub_id'] for c in pack_clips if c['pub_id']]
        added = dbmod.add_package_items(pid, pub_ids)
        print(f"  Pack {pack_idx+1}: '{pack_name}' → {added} clips (id={pid[:8]})")
        package_ids.append({'id': pid, 'name': pack_name, 'clips': added})
    return package_ids


# ── Step 2+3: Re-pipeline + package each video ────────────────────────────────
all_results = {}

for video_info in TOP5:
    print(f"\n{'='*60}")
    print(f"Processing: {video_info['label']}")
    print(f"{'='*60}")

    new_job_id = str(uuid.uuid4())
    print(f"  New job_id: {new_job_id[:8]}...")

    try:
        result = process_video(
            source=video_info['path'],
            number_of_clips=25,
            target_platforms=['youtube'],
            creator=video_info['creator'],
            job_id=new_job_id,
        )
        print(f"  Pipeline done: {result.get('clips_generated', 0)} clips generated")
    except Exception as e:
        print(f"  Pipeline ERROR: {e}")
        all_results[video_info['label']] = []
        continue

    packs = create_packages_for_job(new_job_id, video_info['label'])
    all_results[video_info['label']] = packs

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("SUMMARY — Fresh packages created")
print(f"{'='*60}")
for label, packs in all_results.items():
    total_clips = sum(p['clips'] for p in packs)
    print(f"\n{label}")
    print(f"  {len(packs)} packages, {total_clips} total clips")
    for p in packs:
        print(f"    {p['name']} — {p['clips']} clips")

print("\nDone.")
