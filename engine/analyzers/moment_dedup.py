"""Post-scoring moment deduplication — selects one clip per narrative moment.

Called at pipeline step 7.75, after virality scoring and before the skills
advisor + final render selection.  Works on the full scored candidate list
(not just the top-N finalists) to catch all duplicates.

Algorithm
---------
1. Build a direct-overlap graph:
   Two candidates are "same moment" if BOTH hold:
   a) coverage_ratio >= COVERAGE_THRESHOLD
      coverage_ratio = intersection / min(dur_a, dur_b)
      This catches containment (B mostly inside A) without penalising
      different absolute lengths.
   b) shared_content_ratio >= WORDS_THRESHOLD
      Fraction of non-stop content words shared between their transcript
      segments.  Prevents grouping clips that merely happen to touch the
      same timestamp but discuss different topics.

2. Greedy grouping (no chaining):
   Process candidates in descending virality_score order.  When candidate A
   is claimed by a group, only candidates that DIRECTLY overlap A (per rule
   above) join A's group.  C is not pulled in just because it overlaps B.
   This enforces the encargo rule: A–B–C overlap chain ≠ same moment.

3. Winner selection within a group:
   Score each candidate on a quality composite:
     quality = virality_score
               - duration_penalty   (outside 20–55 s window)
               - dead_air_penalty   (first/last word far from clip boundary)
   Pick the highest quality score; stable tiebreak by shorter duration.

4. Persistence:
   - Winners: status kept as-is (DETECTED), moment_group_id set (or NULL
     for singletons), group_evidence written.
   - Alternatives: status → GROUPED_ALT, moment_group_id and group_evidence
     written.

Cross-job dedup
---------------
Before grouping within the current job, check if the same video already has
REPRESENTATIVE clips rendered in previous jobs that overlap any candidate.
Those older clips are not altered; the new candidate is archived instead,
pointing at the existing clip via group_evidence.
"""
from __future__ import annotations

import json
import uuid
import re
import logging
from typing import Optional

from engine import database as db

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
COVERAGE_THRESHOLD = 0.50   # >= 50% of shorter clip inside longer → same zone
WORDS_THRESHOLD    = 0.25   # >= 25% shared content words → same topic
IDEAL_MIN_DUR      = 20.0   # seconds — shorter clips lose quality points
IDEAL_MAX_DUR      = 55.0   # seconds — longer clips lose quality points
DEAD_AIR_PENALTY   = 5.0    # virality points deducted per second of leading/trailing silence
SIMILAR_SCORE_BAND = 3.0    # within this quality difference, prefer the longer clip

_STOP_WORDS = frozenset(
    "a al con de del el en es la las le lo los más me mi no nos o para"
    " por que se si su sus te un una uno y yo".split()
)


# ── Public API ────────────────────────────────────────────────────────────────

def deduplicate_moments(
    scored: list[dict],
    words: list[dict],
    job_id: str,
) -> tuple[list[dict], dict]:
    """Deduplicate candidates and return (representatives, report).

    Parameters
    ----------
    scored : list of candidate dicts already sorted by virality_score desc
    words  : word-level transcript list for this video
    job_id : current pipeline job id (used for cross-job dedup lookup)

    Returns
    -------
    representatives : list of winner dicts (subset of scored), same sort order
    report : {"groups": int, "archived": int, "cross_job_archived": int}
    """
    if not scored:
        return scored, {"groups": 0, "archived": 0, "cross_job_archived": 0}

    video_id = scored[0].get("video_id") if scored else None
    cross_archived = 0

    # ── Step 0: cross-job dedup ──────────────────────────────────────────────
    # Mark candidates that duplicate a clip already rendered in a prior job
    # on the same video.  Alter the candidate's status in-place so it's
    # excluded from the within-job grouping below.
    existing_clips = _get_existing_clips_for_video(video_id, exclude_job=job_id)
    remaining = []
    for cand in scored:
        conflict = _find_existing_conflict(cand, existing_clips, words)
        if conflict:
            _persist_grouped_alt(
                cand["id"],
                group_id=None,
                evidence={
                    "reason": "cross_job_duplicate",
                    "existing_clip_id": conflict["clip_id"],
                    "existing_job_id": conflict["job_id"],
                    "overlap_ratio": round(conflict["coverage"], 3),
                    "shared_words": round(conflict["words_ratio"], 3),
                },
            )
            cross_archived += 1
        else:
            remaining.append(cand)

    if not remaining:
        return [], {"groups": 0, "archived": len(scored), "cross_job_archived": cross_archived}

    # ── Step 1: build overlap pairs ──────────────────────────────────────────
    pairs: dict[str, set[str]] = {c["id"]: set() for c in remaining}
    for i, a in enumerate(remaining):
        for b in remaining[i + 1:]:
            if _same_moment(a, b, words):
                pairs[a["id"]].add(b["id"])
                pairs[b["id"]].add(a["id"])

    # ── Step 2: greedy grouping (no chaining) ────────────────────────────────
    claimed: set[str] = set()
    groups: list[list[dict]] = []   # each element is list of candidate dicts

    for cand in remaining:   # already sorted by virality_score desc
        if cand["id"] in claimed:
            continue
        # Start a new group centered on this candidate
        group = [cand]
        claimed.add(cand["id"])
        for other_id in pairs[cand["id"]]:
            if other_id not in claimed:
                other = next(c for c in remaining if c["id"] == other_id)
                group.append(other)
                claimed.add(other_id)
        groups.append(group)

    # ── Step 3: winner selection and persistence ──────────────────────────────
    representatives: list[dict] = []
    total_archived  = cross_archived
    real_groups     = 0   # groups with > 1 member

    for group in groups:
        if len(group) == 1:
            # Singleton — no dedup needed; keep as representative
            representatives.append(group[0])
            continue

        real_groups += 1
        group_id = str(uuid.uuid4())
        winner   = _pick_winner(group, words)
        alts     = [c for c in group if c["id"] != winner["id"]]

        # Build evidence payload for each member
        word_overlaps = {
            c["id"]: round(_shared_content_ratio(winner, c, words), 3)
            for c in alts
        }
        coverage_ratios = {
            c["id"]: round(_coverage_ratio(winner, c), 3)
            for c in alts
        }

        winner_evidence = {
            "role": "representative",
            "group_size": len(group),
            "alternatives": [c["id"] for c in alts],
            "winner_reason": _winner_reason(winner, alts, words),
        }
        _persist_representative(winner["id"], group_id, winner_evidence)

        for alt in alts:
            alt_evidence = {
                "role": "grouped_alt",
                "representative_id": winner["id"],
                "coverage_ratio": coverage_ratios[alt["id"]],
                "shared_words_ratio": word_overlaps[alt["id"]],
                "winner_start_s": winner["start_s"],
                "winner_end_s": winner["end_s"],
            }
            _persist_grouped_alt(alt["id"], group_id, alt_evidence)
            total_archived += 1

        representatives.append(winner)

    return representatives, {
        "groups": real_groups,
        "archived": total_archived,
        "cross_job_archived": cross_archived,
    }


# ── Overlap / similarity helpers ──────────────────────────────────────────────

def _coverage_ratio(a: dict, b: dict) -> float:
    """Intersection / min(dur_a, dur_b) — how much of the shorter clip is inside the longer."""
    intersection = max(0.0, min(a["end_s"], b["end_s"]) - max(a["start_s"], b["start_s"]))
    dur_a = a["end_s"] - a["start_s"]
    dur_b = b["end_s"] - b["start_s"]
    min_dur = min(dur_a, dur_b)
    return intersection / min_dur if min_dur > 0 else 0.0


def _content_words(words: list[dict], start: float, end: float) -> frozenset[str]:
    """Non-stop word stems in the window [start, end]."""
    stems = set()
    for w in words:
        if w["start"] >= start and w["end"] <= end:
            tok = re.sub(r"[^a-záéíóúüñA-Z]", "", w["word"].lower())
            if len(tok) >= 3 and tok not in _STOP_WORDS:
                stems.add(tok[:6])   # crude stem: first 6 chars
    return frozenset(stems)


def _shared_content_ratio(a: dict, b: dict, words: list[dict]) -> float:
    words_a = _content_words(words, a["start_s"], a["end_s"])
    words_b = _content_words(words, b["start_s"], b["end_s"])
    if not words_a and not words_b:
        return 0.0
    shared = words_a & words_b
    return len(shared) / max(len(words_a), len(words_b))


def _same_moment(a: dict, b: dict, words: list[dict]) -> bool:
    cov = _coverage_ratio(a, b)
    if cov < COVERAGE_THRESHOLD:
        return False
    # Fast path: very high containment → skip word check
    if cov >= 0.80:
        return True
    return _shared_content_ratio(a, b, words) >= WORDS_THRESHOLD


# ── Winner selection ──────────────────────────────────────────────────────────

def _quality_score(cand: dict, words: list[dict]) -> float:
    base = float(cand.get("virality_score") or 0.0)

    # Duration penalty
    dur = cand["end_s"] - cand["start_s"]
    if dur < IDEAL_MIN_DUR:
        base -= (IDEAL_MIN_DUR - dur) * 1.0
    elif dur > IDEAL_MAX_DUR:
        base -= (dur - IDEAL_MAX_DUR) * 0.5

    # Dead-air penalties (leading/trailing silence)
    first_word = next((w for w in words if w["start"] >= cand["start_s"]), None)
    last_word  = next((w for w in reversed(words) if w["end"] <= cand["end_s"]), None)

    if first_word:
        lead = first_word["start"] - cand["start_s"]
        if lead > 1.5:
            base -= min(lead - 1.5, 3.0) * DEAD_AIR_PENALTY
    if last_word:
        trail = cand["end_s"] - last_word["end"]
        if trail > 2.0:
            base -= min(trail - 2.0, 3.0) * (DEAD_AIR_PENALTY * 0.5)

    return base


def _pick_winner(group: list[dict], words: list[dict]) -> dict:
    scored = [(c, _quality_score(c, words)) for c in group]
    scored.sort(key=lambda x: -x[1])
    best_q = scored[0][1]
    # Candidates within SIMILAR_SCORE_BAND of the best quality → prefer the longest
    similar = [(c, q) for c, q in scored if best_q - q <= SIMILAR_SCORE_BAND]
    similar.sort(key=lambda x: -(x[0]["end_s"] - x[0]["start_s"]))
    return similar[0][0]


def _winner_reason(winner: dict, alts: list[dict], words: list[dict]) -> str:
    wq = _quality_score(winner, words)
    reasons = [f"virality={winner.get('virality_score', 0):.1f}"]
    dur = winner["end_s"] - winner["start_s"]
    if IDEAL_MIN_DUR <= dur <= IDEAL_MAX_DUR:
        reasons.append(f"dur={dur:.0f}s (optimal range)")
    for alt in alts:
        aq = _quality_score(alt, words)
        reasons.append(f"vs alt {alt['id'][:8]} quality_diff={wq - aq:.1f}")
    return "; ".join(reasons)


# ── Cross-job dedup helpers ───────────────────────────────────────────────────

def _get_existing_clips_for_video(video_id: Optional[str], exclude_job: str) -> list[dict]:
    """Return rendered clips for this video from other completed jobs."""
    if not video_id:
        return []
    try:
        with db.db() as conn:
            rows = conn.execute(
                """SELECT cl.id as clip_id, ca.job_id, ca.start_s, ca.end_s
                   FROM clips cl
                   JOIN candidates ca ON ca.id = cl.candidate_id
                   WHERE ca.video_id = ?
                     AND ca.job_id != ?
                     AND ca.status != 'GROUPED_ALT'
                   ORDER BY cl.created_at""",
                (video_id, exclude_job),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _find_existing_conflict(
    cand: dict,
    existing: list[dict],
    words: list[dict],
) -> Optional[dict]:
    """Return the first existing clip that is 'same moment' as cand, or None."""
    for ex in existing:
        cov = _coverage_ratio(cand, ex)
        if cov >= COVERAGE_THRESHOLD:
            wr = _shared_content_ratio(cand, ex, words) if cov < 0.80 else 1.0
            if wr >= WORDS_THRESHOLD:
                return {**ex, "coverage": cov, "words_ratio": wr}
    return None


# ── DB persistence ────────────────────────────────────────────────────────────

def _persist_representative(cand_id: str, group_id: str, evidence: dict) -> None:
    db.update_candidate(cand_id,
        moment_group_id=group_id,
        group_evidence=json.dumps(evidence),
    )


def _persist_grouped_alt(cand_id: str, group_id: Optional[str], evidence: dict) -> None:
    db.update_candidate(cand_id,
        status="GROUPED_ALT",
        moment_group_id=group_id or "",
        group_evidence=json.dumps(evidence),
    )
