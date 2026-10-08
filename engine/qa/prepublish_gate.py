"""Pre-publish gate: FAIL CLOSED. Never publish on uncertainty."""
import json
from engine.config import CONFIG
from engine import database as db

# Coverage threshold: fraction of shorter clip that must overlap to count as duplicate
_DUP_COVERAGE = 0.50


def _coverage_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    intersection = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    dur_a = a_end - a_start
    dur_b = b_end - b_start
    min_dur = min(dur_a, dur_b)
    return intersection / min_dur if min_dur > 0 else 0.0


def _find_duplicate_already_queued(conn, video_id: str, start_s: float, end_s: float,
                                    exclude_clip_id: str) -> dict | None:
    """Return first clip from same video+time zone already PUBLISH-queued or uploaded."""
    # Check prepublish_decisions for clips from the same video already decided PUBLISH
    rows = conn.execute(
        """SELECT pd.clip_id, pd.decision, ca.start_s, ca.end_s
           FROM prepublish_decisions pd
           JOIN clips cl ON cl.id = pd.clip_id
           JOIN candidates ca ON ca.id = cl.candidate_id
           WHERE ca.video_id = ?
             AND pd.clip_id != ?
             AND pd.decision = 'PUBLISH'
           ORDER BY pd.created_at""",
        (video_id, exclude_clip_id),
    ).fetchall()
    for r in rows:
        cov = _coverage_ratio(start_s, end_s, r["start_s"], r["end_s"])
        if cov >= _DUP_COVERAGE:
            return {"clip_id": r["clip_id"], "source": "prepublish_queued", "coverage": round(cov, 3)}

    # Check publish_log for clips already uploaded from same video
    uploaded = conn.execute(
        """SELECT pl.clip_id, ca.start_s, ca.end_s
           FROM publish_log pl
           JOIN clips cl ON cl.id = pl.clip_id
           JOIN candidates ca ON ca.id = cl.candidate_id
           WHERE ca.video_id = ?
             AND pl.clip_id != ?
             AND pl.status = 'SUCCESS'
           ORDER BY pl.published_at""",
        (video_id, exclude_clip_id),
    ).fetchall()
    for r in uploaded:
        cov = _coverage_ratio(start_s, end_s, r["start_s"], r["end_s"])
        if cov >= _DUP_COVERAGE:
            return {"clip_id": r["clip_id"], "source": "already_uploaded", "coverage": round(cov, 3)}

    return None


def run_prepublish_gate(job_id: str, clip_ids: list[str],
                         platforms: list[str]) -> dict[str, str]:
    """Returns {clip_id: 'PUBLISH'|'REVIEW'|'REJECT'}."""
    decisions = {}
    with db.db() as conn:
        for clip_id in clip_ids:
            row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
            cand = conn.execute(
                "SELECT * FROM candidates WHERE id=?", (row["candidate_id"],)
            ).fetchone()

            blocking = []

            # Mandatory checks — FAIL CLOSED
            if row["technical_qa"] == "FAIL":
                blocking.append("technical_qa_failed")
            if row["visual_qa"] == "FAIL":
                blocking.append("visual_qa_failed")

            video = conn.execute(
                "SELECT * FROM videos WHERE id=("
                "SELECT video_id FROM candidates WHERE id=?)", (cand["id"],)
            ).fetchone()

            if blocking:
                decision = "REJECT"
                score = 0.0
            else:
                # Score-based decision
                virality = cand["virality_score"] if cand else 0.0
                platform_scores = json.loads(cand["platform_scores"] or "{}")
                avg_platform = sum(platform_scores.values()) / len(platform_scores) if platform_scores else 50.0

                score = virality * 0.7 + avg_platform * 0.3

                if score >= CONFIG.prepublish.publish_min:
                    decision = "PUBLISH"
                else:
                    decision = "REVIEW"   # always show to user when QA passes

                # Duplicate-moment defense: downgrade to REVIEW if another clip
                # from the same video+time zone is already queued or uploaded.
                # Does not REJECT — lets the user make the final call.
                if decision == "PUBLISH" and video and cand:
                    dup = _find_duplicate_already_queued(
                        conn,
                        video["id"],
                        float(cand["start_s"]),
                        float(cand["end_s"]),
                        clip_id,
                    )
                    if dup:
                        decision = "REVIEW"
                        blocking.append(
                            f"duplicate_moment_already_{dup['source']}"
                            f"::{dup['clip_id'][:8]}(cov={dup['coverage']})"
                        )

            conn.execute(
                "UPDATE clips SET prepublish_decision=?, prepublish_score=? WHERE id=?",
                (decision, round(score, 2), clip_id)
            )
            conn.execute(
                "INSERT INTO prepublish_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (db.new_id(), clip_id, job_id, decision, round(score, 2),
                 row["technical_qa"], row["visual_qa"],
                 int(video["rights_verified"] if video else 0),
                 json.dumps(json.loads(cand["platform_scores"] or "{}") if cand else {}),
                 json.dumps(blocking), db.now())
            )
            decisions[clip_id] = decision

    return decisions
