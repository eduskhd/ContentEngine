"""Series detector: groups candidate moments into multi-part narrative sequences."""
import json
from engine import database as db
from engine.analyzers.semantic_analyzer import analyze_segment, find_smart_end, find_smart_start

# Maximum gap between candidates to be considered the same narrative (seconds)
MAX_NARRATIVE_GAP = 120.0
# Minimum total arc length to justify a series
MIN_SERIES_DURATION = 60.0
# Target part duration
TARGET_PART_S = 30.0
MIN_PART_S = 18.0
MAX_PART_S = 45.0


def detect_series(job_id: str, video_id: str, candidates: list[dict],
                  words: list[dict]) -> list[str]:
    """
    Groups adjacent candidates into narrative series. Returns list of series IDs.
    Updates each candidate in a series with series_id and series_part.
    """
    if not candidates or not words:
        return []

    sorted_cands = sorted(candidates, key=lambda c: c["start_s"])
    groups = _cluster_candidates(sorted_cands)

    series_ids = []
    for group in groups:
        if len(group) < 2:
            continue
        arc_start = group[0]["start_s"]
        arc_end = group[-1]["end_s"]
        arc_duration = arc_end - arc_start
        if arc_duration < MIN_SERIES_DURATION:
            continue

        sid = _create_series_from_group(job_id, video_id, group, words,
                                        arc_start, arc_end)
        if sid:
            series_ids.append(sid)

    return series_ids


def _cluster_candidates(sorted_cands: list[dict]) -> list[list[dict]]:
    """Group candidates that form a continuous narrative arc."""
    if not sorted_cands:
        return []
    groups = []
    current = [sorted_cands[0]]
    for cand in sorted_cands[1:]:
        prev_end = current[-1]["end_s"]
        gap = cand["start_s"] - prev_end
        if gap <= MAX_NARRATIVE_GAP:
            current.append(cand)
        else:
            groups.append(current)
            current = [cand]
    groups.append(current)
    return groups


def _create_series_from_group(job_id, video_id, group, words,
                               arc_start, arc_end) -> str | None:
    """Split a candidate group into series parts and save to DB."""
    arc_duration = arc_end - arc_start
    max_parts = min(4, max(2, int(arc_duration / TARGET_PART_S)))

    # Analyse the full arc for semantic signals
    arc_sem = analyze_segment(words, arc_start, arc_end)

    # Generate split points using natural boundaries
    parts = _split_arc(words, arc_start, arc_end, max_parts)
    if len(parts) < 2:
        return None

    # Score the series
    avg_hook = arc_sem["hook_strength"]
    avg_emotion = arc_sem["emotion_score"]
    story = arc_sem["story_structure"]
    narrative_coherence = (
        (0.4 if story["has_setup"] else 0.0) +
        (0.3 if story["has_escalation"] else 0.0) +
        (0.3 if story["has_payoff"] else 0.0)
    )
    cliffhanger_potential = min(1.0, arc_sem["hook_strength"] * 0.6 +
                                     arc_sem["revelation_score"] * 0.4)
    avg_virality = (sum(c.get("virality_score", 50) for c in group) /
                    max(len(group), 1)) / 100.0
    series_score = round((
        narrative_coherence * 0.30 +
        cliffhanger_potential * 0.25 +
        avg_virality * 0.25 +
        avg_hook * 0.10 +
        avg_emotion * 0.10
    ) * 100, 2)

    reasons = _series_reasons(story, cliffhanger_potential, len(parts), series_score)
    title = _generate_title(arc_sem)

    sid = db.create_series(
        job_id=job_id,
        video_id=video_id,
        series_score=series_score,
        total_parts=len(parts),
        series_reasons=reasons,
        original_start=arc_start,
        original_end=arc_end,
        title=title,
    )

    # Tag each candidate with series membership
    part_times = [(s, e) for s, e in parts]
    for cand in group:
        # Which part does this candidate's midpoint fall in?
        mid = (cand["start_s"] + cand["end_s"]) / 2
        part_num = 1
        for i, (ps, pe) in enumerate(part_times):
            if ps <= mid <= pe:
                part_num = i + 1
                break
        db.update_candidate(cand["id"], series_id=sid, series_part=part_num)

    return sid


def _split_arc(words: list[dict], arc_start: float, arc_end: float,
               n_parts: int) -> list[tuple[float, float]]:
    """Split arc into n_parts using natural sentence boundaries."""
    arc_duration = arc_end - arc_start
    base_step = arc_duration / n_parts
    parts = []
    cur_start = arc_start

    for i in range(n_parts):
        if i == n_parts - 1:
            parts.append((round(cur_start, 3), round(arc_end, 3)))
            break
        target_end = cur_start + base_step
        smart_end = find_smart_end(words, target_end, window_s=10.0)
        # Clamp to duration constraints
        actual_end = max(cur_start + MIN_PART_S, min(smart_end, cur_start + MAX_PART_S))
        parts.append((round(cur_start, 3), round(actual_end, 3)))
        cur_start = actual_end

    return [p for p in parts if p[1] - p[0] >= MIN_PART_S]


def _series_reasons(story, cliff, n_parts, score) -> list[str]:
    reasons = []
    if story["has_setup"] and story["has_escalation"] and story["has_payoff"]:
        reasons.append("Complete narrative arc")
    elif story["has_setup"] and story["has_escalation"]:
        reasons.append("Setup with escalation")
    if cliff >= 0.6:
        reasons.append("Strong cliffhanger potential")
    elif cliff >= 0.3:
        reasons.append("Natural cliffhanger points")
    reasons.append(f"{n_parts} distinct story beats")
    if score >= 80:
        reasons.append("High series potential")
    return reasons


def _generate_title(sem: dict) -> str:
    """Generate a short descriptive title hint from semantic signals."""
    if sem["story_structure"]["has_payoff"] and sem["revelation_score"] > 0.3:
        return "Story with Revelation"
    elif sem["conflict_score"] > 0.3:
        return "Conflict Arc"
    elif sem["humor_score"] > 0.3:
        return "Humor Sequence"
    elif sem["emotion_score"] > 0.5:
        return "Emotional Story"
    return "Narrative Sequence"
