"""Pre-publish gate: FAIL CLOSED. Never publish on uncertainty."""
import json
from engine.config import CONFIG
from engine import database as db


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
