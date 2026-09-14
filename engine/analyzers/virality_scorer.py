"""Virality ensemble scorer — 9-component heuristic formula + optional LLM layer.

When ANTHROPIC_API_KEY is set, runs LLM analysis (claude-haiku) on all candidates
and blends the LLM scores into the ensemble for a significant accuracy boost.
Without an API key, falls back to 100% heuristic scoring — same quality as before.
"""
import json
import logging
from engine.config import CONFIG
from engine import database as db
from engine.analyzers.semantic_analyzer import compute_retention_score

logger = logging.getLogger(__name__)

# Heuristic weights (sum = 1.0) — used when no LLM available
VIRALITY_WEIGHTS_HEURISTIC = {
    "semantic_interest":   0.20,
    "hook_strength":       0.20,
    "emotional_intensity": 0.15,
    "standalone_value":    0.10,
    "audio_energy":        0.10,
    "visual_reaction":     0.10,
    "payoff_strength":     0.05,
    "shareability":        0.05,
    "short_form_fit":      0.05,
}

# Blended weights when LLM scores are available (sum = 1.0)
# LLM contributes 30%; heuristics reduced proportionally.
VIRALITY_WEIGHTS_LLM = {
    "llm_score":           0.30,
    "semantic_interest":   0.12,
    "hook_strength":       0.12,
    "emotional_intensity": 0.10,
    "standalone_value":    0.08,
    "audio_energy":        0.08,
    "visual_reaction":     0.08,
    "payoff_strength":     0.05,
    "shareability":        0.04,
    "short_form_fit":      0.03,
}

_VIRALITY_REASON_TRANSLATIONS_ES = {
    "Question-based hook":       "Hook de pregunta",
    "Shock/surprise hook":       "Hook de impacto",
    "Revelation hook":           "Hook de revelación",
    "Comedy hook":               "Hook cómico",
    "Conflict-driven":           "Impulsado por conflicto",
    "Educational hook":          "Hook educativo",
    "Relatable moment":          "Momento identificable",
    "Transformation story":      "Historia de transformación",
    "Strong opening hook":       "Hook de apertura potente",
    "Good hook":                 "Buen hook",
    "High emotional intensity":  "Alta intensidad emocional",
    "Emotional content":         "Contenido emocional",
    "Works independently":       "Funciona de forma independiente",
    "High audio energy":         "Alta energía de audio",
    "Strong visual reaction":    "Fuerte reacción visual",
    "Clear payoff":              "Desenlace claro",
    "Ideal short-form duration": "Duración ideal para short-form",
    "Good short-form length":    "Buena duración para short-form",
    "High shareability":         "Alta capacidad de difusión",
    "Exceptional viral potential": "Potencial viral excepcional",
    "Strong viral signals":      "Fuertes señales virales",
}

SCORE_TIERS = [
    (90, "Exceptional"),
    (80, "High Potential"),
    (70, "Good"),
    (60, "Average"),
    (0,  "Low"),
]


def score_virality(job_id: str, candidates_data: list[dict],
                   words: list[dict] = None,
                   video_duration: float = 0.0) -> list[dict]:
    """Compute enhanced virality scores. Returns sorted list (highest first)."""

    # Attempt LLM analysis (no-op if API key missing or package not installed)
    llm_scores: dict[str, dict] = {}
    if words:
        try:
            from engine.analyzers.llm_analyzer import analyze_candidates_llm
            llm_scores = analyze_candidates_llm(candidates_data, words, job_id=job_id)
            if llm_scores:
                logger.info("LLM analysis: %d/%d candidates scored",
                            len(llm_scores), len(candidates_data))
        except Exception as exc:
            logger.warning("LLM analysis skipped: %s", exc)

    results = []

    for cand in candidates_data:
        bd = cand.get("score_breakdown", {})
        if isinstance(bd, str):
            try:
                bd = json.loads(bd)
            except Exception:
                bd = {}

        start_s = cand.get("start_s", 0.0)
        end_s = cand.get("end_s", 30.0)
        duration = max(end_s - start_s, 1.0)

        # ── Heuristic components ───────────────────────────────────────────────
        semantic_interest   = bd.get("semantic", 0.5)
        hook_strength       = bd.get("hook", 0.5)
        emotional_intensity = bd.get("emotion", 0.3)
        standalone_value    = bd.get("standalone", 0.5)
        shareability        = bd.get("shareability", 0.4)
        revelation          = bd.get("revelation", 0.0)
        humor               = bd.get("humor", 0.0)
        retention_bd        = bd.get("retention", 0.5)

        story = bd.get("story_structure", {})
        if isinstance(story, str):
            try:
                story = json.loads(story)
            except Exception:
                story = {}
        payoff_strength = min(1.0,
            revelation * 0.5 +
            (0.3 if story.get("has_payoff") else 0.0) +
            (0.1 if story.get("has_cliffhanger") else 0.0) +
            humor * 0.1
        )

        audio_energy    = float(cand.get("audio_score",  0.5) or 0.5)
        visual_reaction = float(cand.get("visual_score", 0.5) or 0.5)

        # Short-form fit
        if 20 <= duration <= 60:
            short_form_fit = 1.0
        elif duration < 20:
            short_form_fit = duration / 20.0
        else:
            short_form_fit = max(0.3, 1.0 - (duration - 60) / 60.0)

        # Platform fit bonus
        ps = cand.get("platform_scores", {})
        if isinstance(ps, str):
            try:
                ps = json.loads(ps)
            except Exception:
                ps = {}
        platform_avg = (sum(ps.values()) / len(ps) / 100.0) if ps else 0.65
        short_form_fit = min(1.0, short_form_fit * 0.7 + platform_avg * 0.3)

        retention_score = float(retention_bd)

        # ── LLM blending ───────────────────────────────────────────────────────
        llm = llm_scores.get(cand["id"])
        # Only use LLM if it returned meaningful (non-neutral) scores
        use_llm = bool(
            llm and (
                llm.get("viral_potential", 50) != 50 or
                llm.get("hook_quality", 50) != 50
            )
        )

        if use_llm:
            llm_score = llm["viral_potential"] / 100.0
            # Blend LLM signals with heuristics for robustness
            hook_eff       = hook_strength * 0.4       + (llm["hook_quality"]           / 100.0) * 0.6
            emotional_eff  = emotional_intensity * 0.4 + (llm["emotional_resonance"]    / 100.0) * 0.6
            standalone_eff = standalone_value * 0.4    + (llm["standalone_value"]       / 100.0) * 0.6
            shareability_eff = shareability * 0.4      + (llm["shareability"]           / 100.0) * 0.6

            virality_score = (
                llm_score          * VIRALITY_WEIGHTS_LLM["llm_score"] +
                semantic_interest  * VIRALITY_WEIGHTS_LLM["semantic_interest"] +
                hook_eff           * VIRALITY_WEIGHTS_LLM["hook_strength"] +
                emotional_eff      * VIRALITY_WEIGHTS_LLM["emotional_intensity"] +
                standalone_eff     * VIRALITY_WEIGHTS_LLM["standalone_value"] +
                audio_energy       * VIRALITY_WEIGHTS_LLM["audio_energy"] +
                visual_reaction    * VIRALITY_WEIGHTS_LLM["visual_reaction"] +
                payoff_strength    * VIRALITY_WEIGHTS_LLM["payoff_strength"] +
                shareability_eff   * VIRALITY_WEIGHTS_LLM["shareability"] +
                short_form_fit     * VIRALITY_WEIGHTS_LLM["short_form_fit"]
            ) * 100.0
        else:
            virality_score = (
                semantic_interest   * VIRALITY_WEIGHTS_HEURISTIC["semantic_interest"] +
                hook_strength       * VIRALITY_WEIGHTS_HEURISTIC["hook_strength"] +
                emotional_intensity * VIRALITY_WEIGHTS_HEURISTIC["emotional_intensity"] +
                standalone_value    * VIRALITY_WEIGHTS_HEURISTIC["standalone_value"] +
                audio_energy        * VIRALITY_WEIGHTS_HEURISTIC["audio_energy"] +
                visual_reaction     * VIRALITY_WEIGHTS_HEURISTIC["visual_reaction"] +
                payoff_strength     * VIRALITY_WEIGHTS_HEURISTIC["payoff_strength"] +
                shareability        * VIRALITY_WEIGHTS_HEURISTIC["shareability"] +
                short_form_fit      * VIRALITY_WEIGHTS_HEURISTIC["short_form_fit"]
            ) * 100.0

        # ── Importance score ───────────────────────────────────────────────────
        # Use actual video duration for position bonus; earlier clips score higher.
        # Fall back to a rough estimate if video_duration wasn't passed.
        vdur = video_duration if video_duration > 0 else max(end_s * 3, end_s + 60.0)
        position_bonus = max(0.0, 1.0 - (start_s / max(vdur, 1)) * 0.5)
        importance_score = (
            semantic_interest * 0.50 +
            position_bonus    * 0.30 +
            audio_energy      * 0.20
        ) * 100.0

        # ── Reasons ────────────────────────────────────────────────────────────
        heuristic_reasons = bd.get("reasons", [])
        llm_reasons = llm.get("reasons", []) if llm else []
        lang = bd.get("lang", "en")
        reasons = _build_virality_reasons(
            virality_score, semantic_interest, hook_strength, emotional_intensity,
            standalone_value, audio_energy, visual_reaction, payoff_strength,
            shareability, short_form_fit, duration,
            heuristic_reasons, llm_reasons,
            llm.get("hook_type") if llm else None,
            lang=lang,
        )

        virality_score   = round(min(100.0, max(0.0, virality_score)), 2)
        importance_score = round(min(100.0, max(0.0, importance_score)), 2)
        retention_out    = round(min(100.0, retention_score * 100), 2)

        db.update_candidate(cand["id"],
            virality_score   = virality_score,
            hook_score       = round(hook_strength * 100, 2),
            emotion_score    = round(emotional_intensity * 100, 2),
            retention_score  = retention_out,
            importance_score = importance_score,
            virality_reasons = reasons,
        )

        results.append({
            "id":              cand["id"],
            "start_s":         start_s,
            "end_s":           end_s,
            "virality_score":  virality_score,
            "importance_score": importance_score,
            "retention_score": retention_out,
            "hook_score":      round(hook_strength * 100, 2),
            "visual_score":    round(visual_reaction * 100, 2),
            "audio_score":     round(audio_energy * 100, 2),
            "emotion_score":   round(emotional_intensity * 100, 2),
            "virality_reasons": reasons,
            "tier":            _get_tier(virality_score),
            "llm_scored":      bool(use_llm),
            "hook_type":       (llm.get("hook_type") if llm else bd.get("content_type", "other")),
        })

    results.sort(key=lambda x: x["virality_score"], reverse=True)
    return results


def _get_tier(score: float) -> str:
    for threshold, label in SCORE_TIERS:
        if score >= threshold:
            return label
    return "Low"


def _build_virality_reasons(virality, semantic, hook, emotion, standalone,
                             audio, visual, payoff, shareability, short_form,
                             duration, heuristic_reasons, llm_reasons,
                             hook_type=None, lang="en") -> list[str]:
    # LLM reasons are more precise — start with those
    reasons = list(llm_reasons) if llm_reasons else list(heuristic_reasons)

    # Add hook type label if informative
    if hook_type and hook_type not in ("other", "story"):
        hook_type_labels = {
            "question":       "Question-based hook",
            "shock":          "Shock/surprise hook",
            "revelation":     "Revelation hook",
            "humor":          "Comedy hook",
            "conflict":       "Conflict-driven",
            "educational":    "Educational hook",
            "relatable":      "Relatable moment",
            "transformation": "Transformation story",
        }
        label = hook_type_labels.get(hook_type)
        if lang == "es" and label:
            label = _VIRALITY_REASON_TRANSLATIONS_ES.get(label, label)
        if label and label not in reasons:
            reasons.insert(0, label)

    _r = _VIRALITY_REASON_TRANSLATIONS_ES if lang == "es" else {}

    strong_hook_label = _r.get("Strong opening hook", "Strong opening hook")
    good_hook_label   = _r.get("Good hook", "Good hook")
    if hook >= 0.7 and not any("hook" in r.lower() for r in reasons):
        reasons.insert(min(1, len(reasons)), strong_hook_label)
    elif hook >= 0.5 and not any("hook" in r.lower() for r in reasons):
        reasons.append(good_hook_label)

    hi_emotion_label = _r.get("High emotional intensity", "High emotional intensity")
    emotion_label    = _r.get("Emotional content", "Emotional content")
    if emotion >= 0.6 and not any("emotion" in r.lower() or "intense" in r.lower() or "intensidad" in r.lower() for r in reasons):
        reasons.append(hi_emotion_label)
    elif emotion >= 0.4 and not any("emotion" in r.lower() or "emocional" in r.lower() for r in reasons):
        reasons.append(emotion_label)

    standalone_label = _r.get("Works independently", "Works independently")
    if standalone >= 0.7 and standalone_label not in reasons:
        reasons.append(standalone_label)

    if audio >= 0.75:
        reasons.append(_r.get("High audio energy", "High audio energy"))

    if visual >= 0.75:
        reasons.append(_r.get("Strong visual reaction", "Strong visual reaction"))

    payoff_label = _r.get("Clear payoff", "Clear payoff")
    if payoff >= 0.5 and not any("payoff" in r.lower() or "arc" in r.lower() or "desenlace" in r.lower() for r in reasons):
        reasons.append(payoff_label)

    if 25 <= duration <= 45:
        reasons.append(_r.get("Ideal short-form duration", "Ideal short-form duration"))
    elif 45 < duration <= 60:
        reasons.append(_r.get("Good short-form length", "Good short-form length"))

    if shareability >= 0.65 and not any("share" in r.lower() or "difusión" in r.lower() for r in reasons):
        reasons.append(_r.get("High shareability", "High shareability"))

    if virality >= 85:
        reasons.append(_r.get("Exceptional viral potential", "Exceptional viral potential"))
    elif virality >= 70:
        reasons.append(_r.get("Strong viral signals", "Strong viral signals"))

    # Deduplicate preserving order
    seen = set()
    unique = []
    for r in reasons:
        key = r.lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique[:8]
