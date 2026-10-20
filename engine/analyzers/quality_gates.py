"""Quality Gates for Streamer Intelligence V2.

Four independent gates that operate as safety checks regardless of score.
A candidate may score high but still require manual review or rejection
if it fails a gate.

Gates:
  1. Context Gate  — verifies narrative completeness and cut quality
  2. Duplicate Gate — detects temporal overlaps with same-job candidates + published clips
  3. Technical Gate — checks audio/visual/duration validity
  4. Confidence Gate — flags candidates with insufficient analysis signal

Each gate returns:
  {
    "passed": bool,
    "decision": "ACCEPT" | "REVIEW" | "REJECT",
    "reasons": ["..."],
    "codes": ["GATE_CODE_1", ...]
  }

Combined result:
  run_all_gates() returns the strictest decision across all gates.
"""
import json
import logging

logger = logging.getLogger(__name__)

# Gate decision hierarchy (strictest wins)
_DECISION_RANK = {"REJECT": 2, "REVIEW": 1, "ACCEPT": 0}


# ── Gate 1: Context ───────────────────────────────────────────────────────────

def gate_context(candidate: dict, words: list[dict]) -> dict:
    """Check if the clip makes sense as a standalone piece of content."""
    reasons = []
    codes = []
    decision = "ACCEPT"

    start_s = candidate.get("start_s", 0.0)
    end_s = candidate.get("end_s", 30.0)
    duration = max(end_s - start_s, 0.1)

    seg_words = [w for w in words if w["start"] >= start_s - 0.1 and w["end"] <= end_s + 0.1]

    if not seg_words:
        # No transcript — can't evaluate context
        return {
            "passed": True,
            "decision": "ACCEPT",
            "reasons": ["Sin transcripción — contexto no evaluado"],
            "codes": ["NO_TRANSCRIPT"],
        }

    # Check for mid-sentence start
    first_word = seg_words[0]["word"].lower().strip(".,!?¡¿;:")
    bad_starters = {
        "y", "pero", "porque", "aunque", "sino", "que",
        "lo", "la", "el", "los", "las", "le", "les",
        "su", "sus", "eso", "esto", "ese", "esta",
    }
    if first_word in bad_starters:
        # Check for pause before this word (natural start after pause is OK)
        word_idx = next((i for i, w in enumerate(words) if abs(w["start"] - seg_words[0]["start"]) < 0.01), None)
        has_prior_pause = False
        if word_idx is not None and word_idx > 0:
            pause = words[word_idx]["start"] - words[word_idx - 1]["end"]
            has_prior_pause = pause >= 0.6

        if not has_prior_pause:
            reasons.append(f"El clip empieza con '{first_word}' — posible inicio en medio de frase")
            codes.append("CONTEXT_MID_SENTENCE_START")
            decision = _escalate(decision, "REVIEW")

    # Check for incomplete ending — last word not sentence-ending
    last_word = seg_words[-1]["word"]
    if not last_word.endswith((".", "!", "?", "…", "\"", "'")):
        # Check if there's a word right after (would indicate a cut mid-sentence)
        end_word_idx = next((i for i, w in enumerate(words) if abs(w["end"] - seg_words[-1]["end"]) < 0.01), None)
        if end_word_idx is not None and end_word_idx + 1 < len(words):
            next_word_start = words[end_word_idx + 1]["start"]
            gap = next_word_start - seg_words[-1]["end"]
            if gap < 0.5:  # word continues right after cut
                reasons.append("El clip termina en medio de una frase")
                codes.append("CONTEXT_MID_SENTENCE_END")
                decision = _escalate(decision, "REVIEW")

    # Check LLM narrative completeness
    bd = _parse_breakdown(candidate)
    llm = bd.get("llm_analysis", {}) or {}
    narrative = llm.get("narrative_completeness", 50)
    if narrative < 25:
        reasons.append(f"Narrativa muy incompleta (LLM score: {narrative}/100)")
        codes.append("CONTEXT_INCOMPLETE_NARRATIVE")
        decision = _escalate(decision, "REVIEW")
    elif narrative < 40:
        reasons.append(f"Narrativa posiblemente incompleta (LLM score: {narrative}/100)")
        codes.append("CONTEXT_WEAK_NARRATIVE")
        decision = _escalate(decision, "REVIEW")

    # Duration sanity
    if duration < 10:
        reasons.append(f"Duración muy corta: {duration:.1f}s")
        codes.append("CONTEXT_TOO_SHORT")
        decision = _escalate(decision, "REJECT")

    return {
        "passed": decision == "ACCEPT",
        "decision": decision,
        "reasons": reasons or ["Contexto narrativo aceptable"],
        "codes": codes or ["CONTEXT_OK"],
    }


# ── Gate 2: Duplicates ────────────────────────────────────────────────────────

def gate_duplicates(candidate: dict, all_candidates: list[dict],
                    published_clips: list[dict] = None) -> dict:
    """Check for temporal overlaps with other candidates and published clips."""
    reasons = []
    codes = []
    decision = "ACCEPT"

    cid = candidate.get("id", "")
    start = candidate.get("start_s", 0.0)
    end = candidate.get("end_s", 30.0)
    video_id = candidate.get("video_id", "")

    # Check overlap with same-job candidates
    for other in (all_candidates or []):
        if other.get("id") == cid:
            continue
        if other.get("status") in ("GROUPED_ALT", "REJECTED", "ARCHIVED"):
            continue
        if other.get("video_id") != video_id:
            continue

        o_start = other.get("start_s", 0)
        o_end = other.get("end_s", 30)
        iou = _compute_iou(start, end, o_start, o_end)

        if iou >= 0.85:
            reasons.append(f"Casi idéntico a otro candidato ({_fmt_ts(o_start)}-{_fmt_ts(o_end)})")
            codes.append("DUP_NEAR_IDENTICAL")
            decision = _escalate(decision, "REVIEW")
            break
        elif iou >= 0.5:
            reasons.append(f"Alta superposición con otro candidato ({iou:.0%} overlap)")
            codes.append("DUP_HIGH_OVERLAP")
            decision = _escalate(decision, "REVIEW")
            break

    # Check overlap with published clips from same video
    for clip in (published_clips or []):
        if clip.get("video_id") != video_id:
            continue
        c_start = clip.get("start_s", 0)
        c_end = clip.get("end_s", 30)
        iou = _compute_iou(start, end, c_start, c_end)
        if iou >= 0.5:
            reasons.append(f"Superpone con clip ya publicado ({_fmt_ts(c_start)}-{_fmt_ts(c_end)})")
            codes.append("DUP_ALREADY_PUBLISHED")
            decision = _escalate(decision, "REVIEW")
            break

    # moment_group_id indicates this was deduplicated — it's an archived alternative
    if candidate.get("status") == "GROUPED_ALT":
        reasons.append("Este candidato fue archivado como alternativa por el deduplicador")
        codes.append("DUP_GROUPED_ALT")
        decision = _escalate(decision, "REVIEW")

    return {
        "passed": decision == "ACCEPT",
        "decision": decision,
        "reasons": reasons or ["Sin duplicados detectados"],
        "codes": codes or ["DUP_OK"],
    }


# ── Gate 3: Technical ─────────────────────────────────────────────────────────

def gate_technical(candidate: dict) -> dict:
    """Check audio/visual/duration technical validity."""
    reasons = []
    codes = []
    decision = "ACCEPT"

    start_s = candidate.get("start_s", 0.0)
    end_s = candidate.get("end_s", 30.0)
    duration = end_s - start_s
    audio_score = float(candidate.get("audio_score", 0.5) or 0.5)
    visual_score = float(candidate.get("visual_score", 0.5) or 0.5)

    # Duration checks
    if duration < 10:
        reasons.append(f"Duración crítica: {duration:.1f}s (mínimo 10s para Shorts)")
        codes.append("TECH_DURATION_CRITICAL")
        decision = _escalate(decision, "REJECT")
    elif duration < 15:
        reasons.append(f"Duración baja: {duration:.1f}s")
        codes.append("TECH_DURATION_SHORT")
        decision = _escalate(decision, "REVIEW")
    elif duration > 62:
        reasons.append(f"Duración excede el límite de Shorts: {duration:.1f}s")
        codes.append("TECH_DURATION_LONG")
        decision = _escalate(decision, "REVIEW")

    # Timestamp validity
    if start_s < 0:
        reasons.append("Timestamp de inicio inválido")
        codes.append("TECH_INVALID_START")
        decision = _escalate(decision, "REJECT")
    if end_s <= start_s:
        reasons.append("Timestamp de fin menor o igual al inicio")
        codes.append("TECH_INVALID_TIMESTAMPS")
        decision = _escalate(decision, "REJECT")

    # Audio quality
    if audio_score < 0.15:
        reasons.append(f"Señal de audio muy débil ({audio_score:.2f})")
        codes.append("TECH_POOR_AUDIO")
        decision = _escalate(decision, "REVIEW")

    # Visual quality
    if visual_score < 0.15:
        reasons.append(f"Señal visual muy débil ({visual_score:.2f})")
        codes.append("TECH_POOR_VISUAL")
        decision = _escalate(decision, "REVIEW")

    return {
        "passed": decision == "ACCEPT",
        "decision": decision,
        "reasons": reasons or ["Parámetros técnicos correctos"],
        "codes": codes or ["TECH_OK"],
    }


# ── Gate 4: Confidence ────────────────────────────────────────────────────────

def gate_confidence(candidate: dict, words: list[dict],
                    min_confidence: float = 0.35) -> dict:
    """Flag candidates where the analysis has insufficient signal."""
    reasons = []
    codes = []
    decision = "ACCEPT"

    start_s = candidate.get("start_s", 0.0)
    end_s = candidate.get("end_s", 30.0)

    seg_words = [w for w in words if w["start"] >= start_s - 0.1 and w["end"] <= end_s + 0.1]
    word_count = len(seg_words)

    # Very few words
    if word_count < 3:
        reasons.append(f"Muy pocas palabras transcritas ({word_count}) — análisis poco fiable")
        codes.append("CONF_FEW_WORDS")
        decision = _escalate(decision, "REVIEW")
    elif word_count < 10:
        reasons.append(f"Pocas palabras transcritas ({word_count})")
        codes.append("CONF_LOW_WORDS")
        decision = _escalate(decision, "REVIEW")

    # Check if score is essentially default/neutral (may indicate failed analysis)
    virality = float(candidate.get("virality_score", 0) or 0)
    if virality == 0.0:
        reasons.append("Score de viralidad en 0 — posible fallo de análisis")
        codes.append("CONF_ZERO_VIRALITY")
        decision = _escalate(decision, "REVIEW")

    # Check word confidence from breakdown
    bd = _parse_breakdown(candidate)
    reasons_list = bd.get("reasons", [])
    if not reasons_list and word_count >= 10:
        reasons.append("Sin razones de selección generadas — señal débil")
        codes.append("CONF_NO_REASONS")
        decision = _escalate(decision, "REVIEW")

    return {
        "passed": decision == "ACCEPT",
        "decision": decision,
        "reasons": reasons or ["Confianza del análisis suficiente"],
        "codes": codes or ["CONF_OK"],
    }


# ── Combined runner ────────────────────────────────────────────────────────────

def run_all_gates(
    candidate: dict,
    words: list[dict],
    all_candidates: list[dict] = None,
    published_clips: list[dict] = None,
    min_confidence: float = 0.35,
) -> dict:
    """Run all 4 quality gates and return the combined strictest result.

    Returns:
        {
            "final_decision": "ACCEPT" | "REVIEW" | "REJECT",
            "gates": {
                "context": {...},
                "duplicates": {...},
                "technical": {...},
                "confidence": {...},
            },
            "blocking_reasons": [...],
            "all_codes": [...],
        }
    """
    results = {
        "context":    gate_context(candidate, words),
        "duplicates": gate_duplicates(candidate, all_candidates or [], published_clips),
        "technical":  gate_technical(candidate),
        "confidence": gate_confidence(candidate, words, min_confidence),
    }

    # Strictest decision across all gates
    final_decision = "ACCEPT"
    blocking_reasons = []
    all_codes = []

    for gate_name, gate_result in results.items():
        d = gate_result["decision"]
        if _DECISION_RANK[d] > _DECISION_RANK[final_decision]:
            final_decision = d
        if d != "ACCEPT":
            blocking_reasons.extend(gate_result["reasons"])
        all_codes.extend(gate_result["codes"])

    return {
        "final_decision": final_decision,
        "gates": results,
        "blocking_reasons": list(set(blocking_reasons)),
        "all_codes": list(set(all_codes)),
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _escalate(current: str, new: str) -> str:
    if _DECISION_RANK[new] > _DECISION_RANK[current]:
        return new
    return current


def _compute_iou(s1: float, e1: float, s2: float, e2: float) -> float:
    intersection = max(0, min(e1, e2) - max(s1, s2))
    union = max(e1, e2) - min(s1, s2)
    return intersection / union if union > 0 else 0.0


def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _parse_breakdown(candidate: dict) -> dict:
    bd = candidate.get("score_breakdown", {})
    if isinstance(bd, str):
        try:
            return json.loads(bd)
        except Exception:
            return {}
    return bd or {}
