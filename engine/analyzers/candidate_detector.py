"""Candidate window detection — semantic-first with sliding-window secondary pass.

v2 improvements:
- Dual-pass detection: sentence-peak pass + sliding-window pass (catches slow-burn moments)
- Type-diversity enforcement: ensures a mix of hook/conflict/humor/revelation/story types
- Better context expansion strategy (adaptive based on sentence score)
- Cliffhanger detection as high-priority boundary signal
"""
import math
from engine.config import CONFIG
from engine import database as db
from engine.analyzers.semantic_analyzer import (
    analyze_segment, find_smart_start, find_smart_end, compute_retention_score,
    HOOK_PHRASES, CLIFFHANGER_WORDS,
)


def detect_candidates(job_id: str, video_id: str, words: list[dict],
                      duration_s: float) -> list[str]:
    """Return list of candidate IDs, ordered by score descending."""
    no_audio = len(words) == 0
    max_cands = CONFIG.target_clips * CONFIG.finalist_multiplier

    if no_audio:
        return _position_based_candidates(job_id, video_id, duration_s, max_cands)

    # Intro/outro skip zones: avoid title cards, CTAs, fade-outs
    intro_cutoff = duration_s * CONFIG.intro_skip_ratio
    outro_cutoff = duration_s * (1.0 - CONFIG.outro_skip_ratio)

    # Pass 1: sentence-peak candidates (existing approach, improved)
    sentence_windows = _sentence_peak_candidates(words, duration_s, max_cands * 2,
                                                  intro_cutoff, outro_cutoff)

    # Pass 2: sliding-window candidates (catches story arcs and slow burns)
    sliding_windows = _sliding_window_candidates(words, duration_s, max_cands,
                                                  intro_cutoff, outro_cutoff)

    # Merge and deduplicate across passes
    all_windows = sentence_windows + sliding_windows
    deduplicated = _deduplicate(all_windows, iou_threshold=CONFIG.deduplicate_iou_threshold)

    # Re-sort by composite score
    deduplicated.sort(key=lambda x: x[2], reverse=True)

    # Diversity-aware selection: ensure we don't just output clones of the same moment
    selected = _select_diverse(deduplicated, max_cands)

    # Persist to DB — drop candidates below minimum quality floor
    cids = []
    for final_start, final_end, score, breakdown, sem, ret in selected:
        if score < CONFIG.min_candidate_composite:
            continue
        cid = db.create_candidate(job_id, video_id, final_start, final_end, score, breakdown)
        db.update_candidate(cid,
            smart_start=final_start,
            smart_end=final_end,
            hook_time=ret["hook_time"],
        )
        cids.append(cid)

    return cids


# ── Pass 1: sentence-peak detection ───────────────────────────────────────────

def _sentence_peak_candidates(words: list[dict], duration_s: float,
                               max_windows: int,
                               intro_cutoff: float = 0.0,
                               outro_cutoff: float = None) -> list[tuple]:
    """Score individual sentences; expand context around top ones."""
    if outro_cutoff is None:
        outro_cutoff = duration_s
    sentences = _segment_sentences(words)
    if not sentences:
        return []

    scored_sentences = []
    for sent in sentences:
        if not sent:
            continue
        s_start = sent[0]["start"]
        s_end = sent[-1]["end"]
        # Skip sentences entirely within intro/outro zones
        if s_end <= intro_cutoff or s_start >= outro_cutoff:
            continue
        sem = analyze_segment(sent, s_start, s_end)
        sentence_score = (
            sem["hook_strength"]     * 0.35 +
            sem["emotion_score"]     * 0.25 +
            sem["semantic_interest"] * 0.25 +
            sem["revelation_score"]  * 0.10 +
            sem["humor_score"]       * 0.05
        )
        scored_sentences.append((s_start, s_end, sentence_score, sem))

    scored_sentences.sort(key=lambda x: x[2], reverse=True)

    raw_windows = []
    for s_start, s_end, peak_score, sem in scored_sentences:
        if len(raw_windows) >= max_windows:
            break

        # Adaptive context expansion: higher peak → more context
        context_back = min(20.0, 10.0 + peak_score * 15.0)
        context_fwd = min(15.0, 8.0 + peak_score * 10.0)
        context_start = max(0.0, s_start - context_back)
        context_end = min(duration_s, s_end + context_fwd)

        smart_s = find_smart_start(words, s_start, window_s=CONFIG.smart_cut_window)
        smart_e = find_smart_end(words, s_end, window_s=CONFIG.smart_cut_window)

        final_start = max(context_start, smart_s)
        final_end = min(context_end, smart_e)

        final_start, final_end = _enforce_duration(final_start, final_end, duration_s)
        if final_end - final_start < CONFIG.min_clip_duration:
            continue

        window_sem = analyze_segment(words, final_start, final_end)
        ret = compute_retention_score(words, final_start, final_end)
        composite = _composite(window_sem, ret)
        breakdown = _build_breakdown(window_sem, ret, final_start, final_end, words)

        raw_windows.append((final_start, final_end, composite, breakdown, window_sem, ret))

    return raw_windows


# ── Pass 2: sliding-window detection ──────────────────────────────────────────

def _sliding_window_candidates(words: list[dict], duration_s: float,
                                max_windows: int,
                                intro_cutoff: float = 0.0,
                                outro_cutoff: float = None) -> list[tuple]:
    """Score overlapping fixed-width windows to catch story arcs and slow burns.

    Generates windows of ~35s with 50% overlap. These complement sentence-peak
    candidates by finding moments that are good overall but don't have a single
    peak sentence.
    """
    if outro_cutoff is None:
        outro_cutoff = duration_s
    if duration_s < 25.0:
        return []

    window_size = 35.0  # seconds
    step = window_size * 0.5  # 50% overlap

    raw_windows = []
    t = max(0.0, intro_cutoff)  # start after intro zone
    while t + window_size <= duration_s + step:
        w_start = round(t, 2)
        w_end = round(min(t + window_size, duration_s), 2)

        # Skip windows that fall in the outro zone
        if w_start >= outro_cutoff:
            break

        if w_end - w_start < CONFIG.min_clip_duration:
            t += step
            continue

        # Quick score using word coverage (skip if no words in window)
        w_in = [w for w in words if w["start"] >= w_start and w["end"] <= w_end]
        if len(w_in) < 5:
            t += step
            continue

        sem = analyze_segment(words, w_start, w_end)
        # Only pursue windows with meaningful signal
        quick_score = sem["semantic_interest"] * 0.5 + sem["hook_strength"] * 0.3 + sem["emotion_score"] * 0.2
        if quick_score < 0.15:
            t += step
            continue

        # Refine boundaries using same smart-cut window as sentence-peak pass
        smart_s = find_smart_start(words, w_start, window_s=CONFIG.smart_cut_window)
        smart_e = find_smart_end(words, w_end, window_s=CONFIG.smart_cut_window)
        final_start = max(0.0, smart_s)
        final_end = min(duration_s, smart_e)

        final_start, final_end = _enforce_duration(final_start, final_end, duration_s)
        if final_end - final_start < CONFIG.min_clip_duration:
            t += step
            continue

        window_sem = analyze_segment(words, final_start, final_end)
        ret = compute_retention_score(words, final_start, final_end)
        composite = _composite(window_sem, ret)
        breakdown = _build_breakdown(window_sem, ret, final_start, final_end, words)

        raw_windows.append((final_start, final_end, composite, breakdown, window_sem, ret))
        t += step

    # Sort and return top candidates
    raw_windows.sort(key=lambda x: x[2], reverse=True)
    return raw_windows[:max_windows]


# ── Diversity-aware selection ──────────────────────────────────────────────────

def _select_diverse(windows: list[tuple], max_n: int) -> list[tuple]:
    """Select top-N candidates while ensuring type diversity.

    Prevents all slots from being filled by variants of the same moment type.
    Allows at most 2 candidates of the same content_type; then falls back to
    pure score ordering once all types are represented.
    """
    if not windows:
        return []

    type_counts: dict[str, int] = {}
    selected = []
    overflow = []

    for window in windows:
        if len(selected) >= max_n:
            break
        _, _, _, breakdown, sem, _ = window
        ctype = sem.get("content_type", "other")

        if type_counts.get(ctype, 0) < 2:
            selected.append(window)
            type_counts[ctype] = type_counts.get(ctype, 0) + 1
        else:
            overflow.append(window)

    # Fill remaining slots with overflow (best score first)
    for window in overflow:
        if len(selected) >= max_n:
            break
        selected.append(window)

    return selected[:max_n]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _composite(sem: dict, ret: dict) -> float:
    return round((
        sem["semantic_interest"] * 0.25 +
        sem["hook_strength"]     * 0.25 +
        sem["emotion_score"]     * 0.15 +
        sem["standalone_value"]  * 0.10 +
        sem["shareability"]      * 0.10 +
        ret["retention_score"]   * 0.15
    ) * 100.0, 2)


def _build_breakdown(sem: dict, ret: dict, start: float, end: float,
                     words: list[dict]) -> dict:
    wps = len([w for w in words if start <= w["start"] <= end]) / max(end - start, 1)
    return {
        "semantic":       round(sem["semantic_interest"], 3),
        "hook":           round(sem["hook_strength"], 3),
        "emotion":        round(sem["emotion_score"], 3),
        "standalone":     round(sem["standalone_value"], 3),
        "shareability":   round(sem["shareability"], 3),
        "conflict":       round(sem["conflict_score"], 3),
        "humor":          round(sem["humor_score"], 3),
        "revelation":     round(sem["revelation_score"], 3),
        "relatability":   round(sem.get("relatability_score", 0.0), 3),
        "educational":    round(sem.get("educational_score", 0.0), 3),
        "retention":      round(ret["retention_score"], 3),
        "hook_time":      round(ret["hook_time"], 2),
        "dead_air":       round(ret["dead_air_ratio"], 3),
        "wps":            round(wps, 2),
        "story_structure": sem["story_structure"],
        "content_type":   sem.get("content_type", "other"),
        "reasons":        sem["reasons"],
    }


def _enforce_duration(start: float, end: float, duration_s: float) -> tuple[float, float]:
    """Clamp segment to min/max duration constraints."""
    clip_dur = end - start
    min_dur = CONFIG.min_clip_duration
    max_dur = getattr(CONFIG, "max_clip_duration", 90.0)

    if clip_dur < min_dur:
        deficit = min_dur - clip_dur
        start = max(0.0, start - deficit / 2)
        end = min(duration_s, end + deficit / 2)

    if end - start > max_dur:
        end = start + max_dur

    return start, end


def _segment_sentences(words: list[dict]) -> list[list[dict]]:
    """Split word list into sentence-like chunks using pauses and punctuation."""
    if not words:
        return []

    sentences = []
    current = [words[0]]

    for i in range(1, len(words)):
        prev = words[i - 1]
        curr = words[i]
        pause = curr["start"] - prev["end"]
        ends_sentence = any(prev["word"].endswith(p) for p in [".", "!", "?"])
        ends_clause = any(prev["word"].endswith(p) for p in [",", ";", ":"])

        # Also split on cliffhanger phrases — they're natural clip boundaries
        cliffhanger_start = any(
            curr["word"].lower().startswith(cw.split()[0]) for cw in CLIFFHANGER_WORDS
            if cw.split()
        )

        if ends_sentence or pause >= 0.6 or (ends_clause and pause >= 0.4) or cliffhanger_start:
            if current:
                sentences.append(current)
            current = [curr]
        else:
            current.append(curr)

    if current:
        sentences.append(current)

    return sentences


def _deduplicate(windows: list[tuple], iou_threshold: float = 0.5) -> list[tuple]:
    """Remove overlapping windows, keeping the higher-scored one."""
    windows_sorted = sorted(windows, key=lambda x: x[2], reverse=True)
    kept = []
    for window in windows_sorted:
        w_start, w_end = window[0], window[1]
        overlap = False
        for kept_w in kept:
            k_start, k_end = kept_w[0], kept_w[1]
            intersection = max(0, min(w_end, k_end) - max(w_start, k_start))
            union = max(w_end, k_end) - min(w_start, k_start)
            iou = intersection / union if union > 0 else 0
            if iou >= iou_threshold:
                overlap = True
                break
        if not overlap:
            kept.append(window)
    return kept


def _position_based_candidates(job_id, video_id, duration_s, max_cands) -> list[str]:
    """Fallback for video-only files: score by position."""
    step = duration_s / max(max_cands, 1)
    cids = []
    for i in range(max_cands):
        start = round(i * step, 2)
        end = round(min(start + 30.0, duration_s), 2)
        if end - start < 10:
            break
        pos_score = max(0.2, 1.0 - (start / max(duration_s, 1)) * 0.5)
        base_score = 30.0 + pos_score * 20.0
        breakdown = {"semantic": 0.0, "hook": 0.0, "emotion": 0.0,
                     "standalone": 0.5, "content_type": "other", "no_audio": True}
        cid = db.create_candidate(job_id, video_id, start, end, base_score, breakdown)
        cids.append(cid)
    return cids
