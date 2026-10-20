"""Smart Boundary Repair Engine — V2.1 experimental.

Analyzes clip boundaries using the word-level transcript and proposes
better start/end timestamps when the cut falls mid-sentence.

Feature flag: CONFIG.SMART_BOUNDARY_REPAIR_ENABLED (default False)

Usage:
    from engine.analyzers.smart_boundary_repair import repair_boundary
    result = repair_boundary(candidate, all_words)

The candidate dict must have: start_s, end_s, id
all_words is the full video transcript (list of {word, start, end, probability})

Returns a RepairResult dict — never raises, never modifies the candidate in place.
"""
import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "smart_boundary_v1"

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_MAX_EXTEND_S = 5.0    # Maximum seconds to search for a cleaner boundary
DEFAULT_MIN_DUR = 10.0        # Minimum clip duration (seconds)
DEFAULT_MAX_DUR = 62.0        # Maximum clip duration (seconds)
MIN_REPAIR_CONFIDENCE = 0.35  # Below this, report NEEDS_REVIEW

# Words that indicate a clip is starting mid-sentence
_MID_SENTENCE_STARTERS = frozenset({
    "y", "e", "pero", "mas", "aunque", "sino", "sino",
    "porque", "para", "que", "cuando", "donde", "como",
    "si", "a", "de", "en", "con", "por",
    "lo", "la", "el", "los", "las", "le", "les",
    "se", "me", "te", "nos", "os",
    "su", "sus", "eso", "esto", "ese", "esta", "estas", "esos",
    "and", "but", "or", "so", "because", "that", "which",
    "who", "when", "where", "how", "if",
})

# Punctuation that ends a sentence
_SENTENCE_END_PUNCT = frozenset(".!?…")
_TERMINAL_PUNCT_RE = re.compile(r'[.!?…]["\'»)]*$')

# Articles that always need a referent — cannot start a standalone clip even after a sentence end
_ARTICLES = frozenset({"el", "la", "los", "las", "le", "les", "lo"})

# Minimum pause between words to be considered a "natural break"
_PAUSE_THRESHOLD_S = 0.5
_LONG_PAUSE_S = 1.0


# ── Public entry point ────────────────────────────────────────────────────────

def repair_boundary(
    candidate: dict,
    all_words: List[dict],
    max_extend_s: float = DEFAULT_MAX_EXTEND_S,
    min_dur: float = DEFAULT_MIN_DUR,
    max_dur: float = DEFAULT_MAX_DUR,
) -> dict:
    """
    Analyze clip boundaries and propose improved timestamps.

    Returns a RepairResult dict with keys:
        original_start, original_end, original_duration
        proposed_start, proposed_end, proposed_duration
        repair_confidence (0–1)
        repair_reasons (list)
        warnings (list)
        repair_status: REPAIRED | UNCHANGED | NEEDS_REVIEW | FAILED
        algorithm_version
        start_diagnosis, end_diagnosis
    """
    orig_start = float(candidate.get("start_s", 0.0))
    orig_end = float(candidate.get("end_s", 0.0))
    orig_dur = orig_end - orig_start
    cid = candidate.get("id", "?")[:12]

    result = _make_result(orig_start, orig_end)

    try:
        return _do_repair(
            cid, orig_start, orig_end, orig_dur,
            all_words, max_extend_s, min_dur, max_dur, result,
        )
    except Exception as exc:
        logger.error(f"[repair] {cid} unexpected error: {exc}")
        result["repair_status"] = "FAILED"
        result["warnings"].append(f"Error interno: {exc}")
        result["repair_confidence"] = 0.0
        return result


def _do_repair(
    cid: str,
    orig_start: float,
    orig_end: float,
    orig_dur: float,
    all_words: List[dict],
    max_extend_s: float,
    min_dur: float,
    max_dur: float,
    result: dict,
) -> dict:
    reasons = []
    warnings = []

    # ── Validate inputs ───────────────────────────────────────────────────────
    video_duration = max((w.get("end", 0) for w in all_words), default=0)
    if not all_words:
        result["repair_status"] = "NEEDS_REVIEW"
        result["warnings"].append("Sin transcripción — no se puede analizar el límite")
        result["repair_confidence"] = 0.0
        result["start_diagnosis"] = "NO_TRANSCRIPT"
        result["end_diagnosis"] = "NO_TRANSCRIPT"
        return result

    if orig_start < 0 or orig_end <= orig_start:
        result["repair_status"] = "FAILED"
        result["warnings"].append(f"Timestamps inválidos: {orig_start:.2f}–{orig_end:.2f}")
        result["repair_confidence"] = 0.0
        return result

    # ── Extract context window ────────────────────────────────────────────────
    ctx_start = max(0.0, orig_start - max_extend_s - 2.0)
    ctx_end = min(video_duration, orig_end + max_extend_s + 2.0)
    ctx_words = [w for w in all_words if _word_in_range(w, ctx_start, ctx_end)]

    seg_words = [w for w in ctx_words if _word_in_range(w, orig_start, orig_end)]

    if not seg_words:
        result["repair_status"] = "NEEDS_REVIEW"
        result["warnings"].append("No hay palabras en el segmento — candidato posiblemente sin diálogo")
        result["repair_confidence"] = 0.2
        result["start_diagnosis"] = "NO_WORDS"
        result["end_diagnosis"] = "NO_WORDS"
        return result

    # ── Diagnose start ────────────────────────────────────────────────────────
    first_word = seg_words[0]
    start_diag, start_confidence, start_reason = _diagnose_start(
        first_word, ctx_words, orig_start,
    )
    result["start_diagnosis"] = start_diag

    # ── Diagnose end ──────────────────────────────────────────────────────────
    last_word = seg_words[-1]
    end_diag, end_confidence, end_reason = _diagnose_end(
        last_word, ctx_words, orig_end,
    )
    result["end_diagnosis"] = end_diag

    if start_reason:
        reasons.append(start_reason)
    if end_reason:
        reasons.append(end_reason)

    # ── Propose repairs ───────────────────────────────────────────────────────
    proposed_start = orig_start
    proposed_end = orig_end
    start_repaired = False
    end_repaired = False

    if start_diag in ("MID_SENTENCE", "PRONOUN_START", "CONNECTOR_START"):
        new_start = _find_clean_start(
            ctx_words, orig_start, max_extend_s=max_extend_s,
        )
        if new_start is not None and new_start < orig_start:
            proposed_start = new_start
            start_repaired = True
            reasons.append(f"Inicio ajustado: {orig_start:.2f}s → {new_start:.2f}s")
        elif new_start is None:
            warnings.append("No se encontró un inicio limpio dentro del margen")
            result["start_diagnosis"] += "_UNREPAIRABLE"

    if end_diag in ("MID_SENTENCE", "ABRUPT_END"):
        new_end = _find_clean_end(
            ctx_words, orig_end, max_extend_s=max_extend_s,
        )
        if new_end is not None and new_end > orig_end:
            proposed_end = new_end
            end_repaired = True
            reasons.append(f"Final ajustado: {orig_end:.2f}s → {new_end:.2f}s")
        elif new_end is None:
            warnings.append("No se encontró un final limpio dentro del margen")
            result["end_diagnosis"] += "_UNREPAIRABLE"

    # ── Validate proposed duration ────────────────────────────────────────────
    proposed_dur = proposed_end - proposed_start

    if proposed_dur < min_dur:
        warnings.append(f"Duración propuesta {proposed_dur:.1f}s < mínimo {min_dur}s — revertiendo")
        proposed_start = orig_start
        proposed_end = orig_end
        proposed_dur = orig_dur
        start_repaired = False
        end_repaired = False

    if proposed_dur > max_dur:
        # Try to salvage: keep end repair, revert start
        if end_repaired and not start_repaired:
            warnings.append(f"Duración propuesta {proposed_dur:.1f}s > máximo {max_dur}s — revertiendo inicio")
            proposed_start = orig_start
            proposed_dur = proposed_end - proposed_start
        elif start_repaired and not end_repaired:
            warnings.append(f"Duración propuesta {proposed_dur:.1f}s > máximo {max_dur}s — revertiendo final")
            proposed_end = orig_end
            proposed_dur = orig_dur
        else:
            warnings.append(f"Duración propuesta {proposed_dur:.1f}s > máximo {max_dur}s — revertiendo ambos")
            proposed_start = orig_start
            proposed_end = orig_end
            proposed_dur = orig_dur
            start_repaired = False
            end_repaired = False

    # ── Detect if repair makes things worse ───────────────────────────────────
    # Don't extend if the new segment starts or ends at exactly the same point
    # (no-op extension)
    if abs(proposed_start - orig_start) < 0.05 and abs(proposed_end - orig_end) < 0.05:
        start_repaired = False
        end_repaired = False

    # ── Compute confidence ────────────────────────────────────────────────────
    confidence = (start_confidence + end_confidence) / 2.0

    # Penalize if both boundaries had issues but neither could be repaired
    if start_diag != "OK" and "_UNREPAIRABLE" in result.get("start_diagnosis", ""):
        confidence *= 0.5
    if end_diag != "OK" and "_UNREPAIRABLE" in result.get("end_diagnosis", ""):
        confidence *= 0.5

    result["repair_confidence"] = round(confidence, 3)
    result["repair_reasons"] = reasons
    result["warnings"] = warnings
    result["proposed_start"] = round(proposed_start, 3)
    result["proposed_end"] = round(proposed_end, 3)
    result["proposed_duration"] = round(proposed_dur, 3)

    any_repaired = start_repaired or end_repaired
    if any_repaired:
        result["repair_status"] = "REPAIRED"
    elif confidence < MIN_REPAIR_CONFIDENCE and (start_diag != "OK" or end_diag != "OK"):
        result["repair_status"] = "NEEDS_REVIEW"
    else:
        result["repair_status"] = "UNCHANGED"

    return result


# ── Diagnosis helpers ─────────────────────────────────────────────────────────

def _diagnose_start(
    first_word: dict,
    ctx_words: List[dict],
    orig_start: float,
) -> tuple:
    """Return (diagnosis_code, confidence, reason_str)."""
    text = first_word.get("word", "").strip()
    clean = text.lower().strip(".,!?¡¿;:\"'()")

    # Check pause before this word
    prior_words = [w for w in ctx_words if w.get("end", 0) < orig_start - 0.05]
    pause_before = 0.0
    if prior_words:
        pause_before = orig_start - prior_words[-1].get("end", orig_start)

    # Natural break: long pause or no prior words (genuine start)
    if pause_before >= _LONG_PAUSE_S or not prior_words:
        return ("OK", 0.90, "")

    # Check if previous word ends with sentence-terminating punctuation FIRST.
    # Exception: articles (el/la/los/las) always need a referent and cannot start
    # a standalone clip even when the previous sentence ended cleanly.
    if prior_words:
        prev_text = prior_words[-1].get("word", "")
        if _TERMINAL_PUNCT_RE.search(prev_text) and clean not in _ARTICLES:
            return ("OK", 0.85, "")

    if clean in _MID_SENTENCE_STARTERS:
        # Short pause + connector → almost certainly mid-sentence
        if pause_before < _PAUSE_THRESHOLD_S:
            return ("CONNECTOR_START", 0.35,
                    f"El clip empieza con conector '{text}' — posible inicio en mitad de frase")
        else:
            # Moderate pause — uncertain
            return ("PRONOUN_START", 0.55,
                    f"El clip empieza con '{text}' — inicio a verificar")

    # First letter uppercase after a meaningful pause — likely OK
    if text and text[0].isupper() and pause_before >= _PAUSE_THRESHOLD_S:
        return ("OK", 0.75, "")

    # If first word is uppercase and previous word doesn't end in punct →
    # could still be mid-sentence (names, proper nouns)
    if text and text[0].isupper():
        return ("OK", 0.65, "")

    # Lowercase start with short pause — likely mid-sentence
    if text and text[0].islower() and pause_before < _PAUSE_THRESHOLD_S:
        return ("MID_SENTENCE", 0.40,
                f"El clip empieza en minúsculas ('{text}') con pausa corta — probable mitad de frase")

    return ("OK", 0.70, "")


def _diagnose_end(
    last_word: dict,
    ctx_words: List[dict],
    orig_end: float,
) -> tuple:
    """Return (diagnosis_code, confidence, reason_str)."""
    text = last_word.get("word", "").strip()
    word_end = last_word.get("end", orig_end)

    # Check if word ends with terminal punctuation
    if _TERMINAL_PUNCT_RE.search(text):
        return ("OK", 0.90, "")

    # Check pause after last word
    following = [w for w in ctx_words if w.get("start", 0) > word_end + 0.05]
    if not following:
        # No more words — natural end
        return ("OK", 0.80, "")

    gap = following[0].get("start", orig_end) - word_end

    if gap >= _LONG_PAUSE_S:
        # Long pause after last word → natural break even without punctuation
        return ("OK", 0.80, "")

    if gap >= _PAUSE_THRESHOLD_S:
        # Short-moderate pause — could be OK or mid-sentence
        return ("OK", 0.65, "")

    # No punctuation, no pause, words follow immediately → cut mid-sentence
    next_word = following[0].get("word", "")
    return ("ABRUPT_END", 0.35,
            f"El clip termina abruptamente antes de '{next_word}' — probable corte en mitad de frase")


# ── Repair search helpers ─────────────────────────────────────────────────────

def _find_clean_start(
    ctx_words: List[dict],
    orig_start: float,
    max_extend_s: float,
) -> Optional[float]:
    """
    Search backwards from orig_start for a natural sentence beginning.
    Returns the proposed new start_s (< orig_start) or None.
    """
    earliest = orig_start - max_extend_s
    candidates = []

    # Get words before the original start
    before = sorted(
        [w for w in ctx_words if w.get("end", 0) < orig_start + 0.1],
        key=lambda w: w.get("start", 0),
    )

    for i, w in enumerate(before):
        ws = w.get("start", 0)
        if ws < earliest:
            continue

        text = w.get("word", "").strip()
        clean = text.lower().strip(".,!?¡¿;:\"'()")

        # Check if this word starts AFTER a long pause (natural start)
        if i > 0:
            prev_end = before[i - 1].get("end", 0)
            pause = ws - prev_end
            if pause >= _LONG_PAUSE_S and clean not in _MID_SENTENCE_STARTERS:
                candidates.append((ws, 0.85, "pausa larga"))
        elif i == 0:
            # First word in context window — only if not a connector/pronoun
            if clean not in _MID_SENTENCE_STARTERS:
                candidates.append((ws, 0.80, "inicio de ventana"))

        # Check if previous word ends a sentence
        if i > 0:
            prev_text = before[i - 1].get("word", "").strip()
            if _TERMINAL_PUNCT_RE.search(prev_text):
                if clean not in _MID_SENTENCE_STARTERS:
                    candidates.append((ws, 0.90, "inicio de oración"))

    if not candidates:
        return None

    # Pick the candidate closest to the original start (prefer minimal change)
    candidates.sort(key=lambda c: abs(c[0] - orig_start))
    return candidates[0][0]


def _find_clean_end(
    ctx_words: List[dict],
    orig_end: float,
    max_extend_s: float,
) -> Optional[float]:
    """
    Search forward from orig_end for a natural sentence ending.
    Returns the proposed new end_s (> orig_end) or None.
    """
    latest = orig_end + max_extend_s
    candidates = []

    # Get words after the original end
    after = sorted(
        [w for w in ctx_words if w.get("start", 0) > orig_end - 0.1],
        key=lambda w: w.get("start", 0),
    )

    for i, w in enumerate(after):
        we = w.get("end", 0)
        if we > latest:
            break

        text = w.get("word", "").strip()

        # Word ends with terminal punctuation
        if _TERMINAL_PUNCT_RE.search(text):
            candidates.append((we, 0.90, f"fin de oración ({text})"))
            break  # take the first one

        # Long pause after this word
        if i + 1 < len(after):
            next_start = after[i + 1].get("start", we)
            pause = next_start - we
            if pause >= _LONG_PAUSE_S:
                candidates.append((we, 0.80, f"pausa larga después de '{text}'"))
                break

    if not candidates:
        return None

    return candidates[0][0]


# ── Utilities ─────────────────────────────────────────────────────────────────

def _word_in_range(w: dict, start: float, end: float) -> bool:
    ws = float(w.get("start", 0))
    we = float(w.get("end", 0))
    return we >= start - 0.1 and ws <= end + 0.1


def _make_result(orig_start: float, orig_end: float) -> dict:
    dur = orig_end - orig_start
    return {
        "original_start": round(orig_start, 3),
        "original_end": round(orig_end, 3),
        "original_duration": round(dur, 3),
        "proposed_start": round(orig_start, 3),
        "proposed_end": round(orig_end, 3),
        "proposed_duration": round(dur, 3),
        "repair_confidence": 0.0,
        "repair_reasons": [],
        "warnings": [],
        "repair_status": "UNCHANGED",
        "algorithm_version": ALGORITHM_VERSION,
        "start_diagnosis": "UNKNOWN",
        "end_diagnosis": "UNKNOWN",
    }


# ── Batch helper ──────────────────────────────────────────────────────────────

def repair_batch(
    candidates: List[dict],
    all_words: List[dict],
    **kwargs,
) -> List[dict]:
    """Run repair_boundary on a list of candidates. Returns parallel list of results."""
    results = []
    for cand in candidates:
        res = repair_boundary(cand, all_words, **kwargs)
        res["candidate_id"] = cand.get("id")
        results.append(res)
    return results


# ── Post-repair duplicate check ───────────────────────────────────────────────

def check_post_repair_overlaps(
    original_candidates: List[dict],
    repair_results: List[dict],
    iou_threshold: float = 0.5,
) -> List[dict]:
    """
    After repair, check if any two repaired clips now overlap significantly.
    Returns list of overlap warnings.
    """
    repaired = []
    for cand, rep in zip(original_candidates, repair_results):
        repaired.append({
            "id": cand.get("id"),
            "start_s": rep["proposed_start"],
            "end_s": rep["proposed_end"],
        })

    warnings = []
    for i, a in enumerate(repaired):
        for j, b in enumerate(repaired):
            if j <= i:
                continue
            iou = _compute_iou(a["start_s"], a["end_s"], b["start_s"], b["end_s"])
            if iou >= iou_threshold:
                warnings.append({
                    "candidate_a": a["id"],
                    "candidate_b": b["id"],
                    "iou": round(iou, 3),
                    "a_range": f"{a['start_s']:.2f}–{a['end_s']:.2f}",
                    "b_range": f"{b['start_s']:.2f}–{b['end_s']:.2f}",
                })
    return warnings


def _compute_iou(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    inter_start = max(start_a, start_b)
    inter_end = min(end_a, end_b)
    inter = max(0.0, inter_end - inter_start)
    if inter == 0:
        return 0.0
    union = (end_a - start_a) + (end_b - start_b) - inter
    return inter / union if union > 0 else 0.0
