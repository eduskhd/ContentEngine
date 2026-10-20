"""Streamer Intelligence Scorer V2 — specialized for Spanish streamers.

Computes a 7-factor viral score optimized for gaming, IRL, and reaction
streaming content in Spanish. Operates as a complementary layer on top of
the existing heuristic + LLM virality pipeline.

Usage:
    from engine.analyzers.streamer_scorer import score_streamer_v2
    v2 = score_streamer_v2(candidate_row, words)

The candidate_row must have score_breakdown populated by the existing pipeline.
No re-analysis is performed on data that has already been computed.
"""
import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SCORE_VERSION = "streamer_v2"
NICHE = "spanish_streamers"

# ── Configurable factor weights (sum = 1.0) ───────────────────────────────────
DEFAULT_WEIGHTS = {
    "hook":        0.25,
    "emotion":     0.20,
    "context":     0.15,
    "engagement":  0.15,
    "rhythm":      0.10,
    "quality":     0.10,
    "originality": 0.05,
}

# ── Streamer-specific Spanish expressions ─────────────────────────────────────
# These extend the generic HOOK_PHRASES_ES from semantic_analyzer.

STREAMER_HOOK_ES = [
    "no me lo puedo creer", "no me lo creo", "pero qué dices", "mira lo que acaba",
    "esto es una locura", "te lo juro", "no puede ser", "escucha esto",
    "espera espera espera", "un momento un momento", "para para para",
    "qué acaba de pasar", "esto es brutal", "lo flipas", "flipante",
    "me estoy muriendo", "me estoy meando", "me estoy partiendo",
    "qué me estás contando", "cómo que", "cómo que no",
    "dios mío dios mío", "ostia tío", "madre mía", "hostia puta",
    "qué fuerte tío", "tío qué fuerte", "chaval mira",
    "venga va ya", "a ver a ver", "espera que",
    "mira mira mira", "fíjate fíjate", "ojo ojo ojo",
]

STREAMER_EMOTION_ES = {
    "reaction": [
        "no me lo puedo creer", "no lo puedo creer", "qué pasada",
        "qué barbaridad", "lo flipas", "flipo en colores",
        "me quedo flipado", "me quedo loco", "me vuela la cabeza",
        "madre mía", "ostia", "hostia", "joder", "coño", "mecachis",
        "jo", "jolín", "atiza", "qué burrada", "bestia", "bruto",
    ],
    "gaming_rage": [
        "me tilto", "me tila", "tilt", "qué rage", "me está rajeando",
        "rage quit", "no me renta", "feeder", "noob", "chetado",
        "hackeado", "hacker", "cheto", "aimbot", "wallhack",
        "la que se está liando", "la que se está montando",
        "qué carreta", "carreta", "ez", "izi", "easy",
        "somos unos cracks", "somos paquetes", "soy un paquete",
        "qué malo soy", "qué paquete", "throw", "fedeó",
    ],
    "excitement_es": [
        "esto es una locura", "de locos", "es una locura total",
        "una burrada", "la bomba", "bombazo", "es la leche",
        "qué crack", "crack total", "geniazo", "la mejor jugada",
        "lo mejor que he visto", "insano", "una locura de nivel",
        "espectacular", "es una pasada", "qué jugadón",
    ],
    "humor_es": [
        "me estoy meando", "me estoy meando de risa", "me estoy partiendo",
        "me parto", "me meo", "jajajaja", "ajajaja", "hahaha",
        "qué gracioso", "esto es muy gracioso", "me da la risa",
        "me parto el ojete", "me parto la caja", "qué crack",
        "esto no puede ser real", "qué meme", "eres un meme",
        "qué chiste", "chiste malo", "es un meme andante",
    ],
    "surprise_es": [
        "no me esperaba esto", "no me lo esperaba", "no lo esperaba",
        "de la nada", "de repente", "inesperado", "me pilló",
        "me cogió por sorpresa", "no me lo crei", "no me lo puedo creer",
        "qué sorpresa", "vaya sorpresa", "sorpresazo",
        "un giro inesperado", "nadie se esperaba",
    ],
}

ENGAGEMENT_SIGNALS_ES = [
    # Direct audience interaction
    "os lo juro", "de verdad os digo", "escuchadme", "ponedme en el chat",
    "qué opináis", "qué pensáis", "decidme en el chat",
    "me comentáis", "dejad en los comentarios",
    "qué haríais vosotros", "qué hubierais hecho",
    "¿vosotros lo sabíais", "¿sabíais que",
    # Controversial / polarizing
    "controversia", "polémico", "la gente se va a enfadar",
    "me van a meter caña", "me van a criticar",
    "seguro que hay haters", "ya sé que dirán",
    # Curiosity gap
    "al final resulta que", "pero lo mejor está por venir",
    "y entonces pasó algo", "hay algo que no os he dicho",
    "tengo que contaros algo", "hay una cosa",
    # Community language
    "mis viewers", "la comunidad", "el chat", "el twitch chat",
    "los subs", "los donadores",
]

RHYTHM_DEAD_TIME_SIGNALS = [
    "ehhh", "eeeh", "umm", "mmm", "bueno", "pues",
    "o sea", "es que", "a ver", "no sé", "como que",
]

# ── Context quality signals ────────────────────────────────────────────────────

BAD_START_PATTERNS = [
    r"^(y|pero|porque|aunque|sino|si|que|lo|la|el|los|las|le|les|su|sus)\b",
    r"^(eso|esto|ese|esta|esos|estas|aquel|aquella)\b",
    r"^(así que|por eso|en ese caso|por lo tanto)\b",
    r"^(como te decía|como os decía|como decia)\b",
    r"^(y luego|y entonces|y después)\b",
]

GOOD_START_SIGNALS = [
    "a ver", "os cuento", "os voy a contar", "mira", "fijaos",
    "tío", "chavales", "hola", "buenas", "qué tal",
    "hoy", "ayer", "el otro día",
    "yo tengo", "yo creo", "yo pienso", "yo diría",
    "estaba", "fui", "vi", "hice", "jugué",
    "me pasó", "pasó algo", "pasó una cosa",
    "resulta que", "básicamente", "la verdad es",
    "tengo que deciros", "voy a contaros",
]

GOOD_END_SIGNALS = [
    ".", "!", "?",
    "increíble", "brutal", "flipante", "una locura",
    "no lo olvidaré", "fue épico", "la mejor",
    "fin de la historia", "y punto", "así de sencillo",
    "menuda historia", "qué vuelta de tuerca",
]


# ── Main scorer ───────────────────────────────────────────────────────────────

def score_streamer_v2(
    candidate: dict,
    words: list[dict],
    all_candidates: list[dict] = None,
    weights: dict = None,
) -> dict:
    """Compute the V2 streamer score for a candidate.

    Args:
        candidate: candidate row dict from DB (with score_breakdown populated)
        words: full word-level transcript for the video
        all_candidates: other candidates in the same job (for originality check)
        weights: override default factor weights (dict must sum to ~1.0)

    Returns:
        V2 score dict with total_score, factors, reasons, warnings, decision
    """
    w = weights or DEFAULT_WEIGHTS
    _validate_weights(w)

    start_s = candidate.get("start_s", 0.0)
    end_s = candidate.get("end_s", 30.0)
    duration = max(end_s - start_s, 1.0)

    # Extract existing analysis from score_breakdown
    bd = _parse_breakdown(candidate)
    llm = bd.get("llm_analysis", {}) or {}

    # Build the segment word list
    seg_words = [wd for wd in words if wd["start"] >= start_s - 0.1 and wd["end"] <= end_s + 0.1]
    seg_text = " ".join(wd["word"] for wd in seg_words).lower()
    first_words = " ".join(wd["word"] for wd in seg_words[:20]).lower()
    last_words = " ".join(wd["word"] for wd in seg_words[-10:]).lower()
    has_transcript = len(seg_words) >= 5

    warnings = []

    # ── Factor 1: Hook (25%) ───────────────────────────────────────────────────
    hook_score, hook_reasons, hook_warnings = _score_hook(
        bd, llm, seg_text, first_words, duration, has_transcript
    )
    warnings.extend(hook_warnings)

    # ── Factor 2: Emotion (20%) ────────────────────────────────────────────────
    emotion_score, emotion_reasons, emotion_warnings = _score_emotion(
        bd, llm, seg_text, has_transcript
    )
    warnings.extend(emotion_warnings)

    # ── Factor 3: Context (15%) ────────────────────────────────────────────────
    context_score, context_reasons, context_warnings = _score_context(
        bd, seg_words, first_words, last_words, duration, has_transcript
    )
    warnings.extend(context_warnings)

    # ── Factor 4: Engagement Potential (15%) ─────────────────────────────────
    engagement_score, engagement_reasons = _score_engagement(
        bd, llm, seg_text, has_transcript
    )

    # ── Factor 5: Rhythm (10%) ────────────────────────────────────────────────
    rhythm_score, rhythm_reasons, rhythm_warnings = _score_rhythm(
        bd, seg_words, duration, has_transcript
    )
    warnings.extend(rhythm_warnings)

    # ── Factor 6: Quality (10%) ───────────────────────────────────────────────
    quality_score, quality_reasons, quality_warnings = _score_quality(
        candidate, duration
    )
    warnings.extend(quality_warnings)

    # ── Factor 7: Originality (5%) ────────────────────────────────────────────
    originality_score, originality_reasons, originality_warnings = _score_originality(
        candidate, all_candidates or []
    )
    warnings.extend(originality_warnings)

    # ── Weighted total ─────────────────────────────────────────────────────────
    factors_raw = {
        "hook":        hook_score,
        "emotion":     emotion_score,
        "context":     context_score,
        "engagement":  engagement_score,
        "rhythm":      rhythm_score,
        "quality":     quality_score,
        "originality": originality_score,
    }

    total = sum(factors_raw[k] * w[k] for k in factors_raw)
    total = round(min(100.0, max(0.0, total)), 1)

    # Confidence: proportional to signal availability
    confidence = _compute_confidence(has_transcript, bool(llm), candidate)

    # Deduplicate reasons
    all_reasons = []
    seen_r = set()
    for r_list in [hook_reasons, emotion_reasons, context_reasons,
                   engagement_reasons, rhythm_reasons, quality_reasons,
                   originality_reasons]:
        for r in r_list:
            if r.lower() not in seen_r:
                seen_r.add(r.lower())
                all_reasons.append(r)

    # Recommended action
    if total >= 75 and context_score >= 50:
        action = "prioritize"
    elif total >= 50 and context_score >= 35:
        action = "generate"
    elif total >= 30:
        action = "review"
    else:
        action = "skip"

    return {
        "score_version":       SCORE_VERSION,
        "niche":               NICHE,
        "total_score":         total,
        "confidence":          round(confidence, 2),
        "factors": {
            k: round(v, 1) for k, v in factors_raw.items()
        },
        "reasons":             all_reasons[:6],
        "warnings":            list(set(warnings))[:4],
        "recommended_action":  action,
    }


# ── Factor implementations ────────────────────────────────────────────────────

def _score_hook(bd, llm, seg_text, first_words, duration, has_transcript):
    reasons = []
    warnings = []

    # From existing breakdown
    existing_hook = bd.get("hook", 0.5)
    llm_hook = llm.get("hook_quality", 50) / 100.0 if llm else existing_hook

    # Blend heuristic + LLM
    base = (existing_hook * 0.5 + llm_hook * 0.5) if llm else existing_hook
    score = base * 100.0

    # Streamer-specific hook bonus
    streamer_hook_hits = sum(1 for p in STREAMER_HOOK_ES if p in first_words)
    if streamer_hook_hits >= 2:
        score = min(100, score + 15)
        reasons.append("Múltiples frases gancho de streamer")
    elif streamer_hook_hits == 1:
        score = min(100, score + 8)
        reasons.append("Frase gancho de streamer detectada")

    # First 3 seconds assessment
    opening_3s = first_words[:100]
    has_exclamation = "!" in opening_3s or "¡" in opening_3s
    has_question = "?" in opening_3s or "¿" in opening_3s
    if has_exclamation:
        score = min(100, score + 5)
        reasons.append("Apertura con exclamación")
    if has_question:
        score = min(100, score + 7)
        reasons.append("Pregunta de apertura — genera curiosidad")

    if score >= 70:
        reasons.append("Hook de apertura fuerte")
    elif score < 35 and has_transcript:
        warnings.append("Hook débil — el inicio puede no retener al espectador")

    return round(score, 1), reasons, warnings


def _score_emotion(bd, llm, seg_text, has_transcript):
    reasons = []
    warnings = []

    existing_emotion = bd.get("emotion", 0.3)
    llm_emotion = llm.get("emotional_resonance", 50) / 100.0 if llm else existing_emotion
    base = (existing_emotion * 0.4 + llm_emotion * 0.6) if llm else existing_emotion
    score = base * 100.0

    # Streamer-specific emotion detection
    reaction_hits = sum(1 for w in STREAMER_EMOTION_ES["reaction"] if w in seg_text)
    gaming_hits = sum(1 for w in STREAMER_EMOTION_ES["gaming_rage"] if w in seg_text)
    excitement_hits = sum(1 for w in STREAMER_EMOTION_ES["excitement_es"] if w in seg_text)
    humor_hits = sum(1 for w in STREAMER_EMOTION_ES["humor_es"] if w in seg_text)
    surprise_hits = sum(1 for w in STREAMER_EMOTION_ES["surprise_es"] if w in seg_text)

    if reaction_hits >= 2:
        score = min(100, score + 12)
        reasons.append("Reacciones auténticas del streamer")
    elif reaction_hits == 1:
        score = min(100, score + 6)

    if humor_hits >= 2:
        score = min(100, score + 10)
        reasons.append("Momento humorístico genuino")
    elif humor_hits == 1:
        score = min(100, score + 5)

    if surprise_hits >= 1:
        score = min(100, score + 8)
        reasons.append("Momento de sorpresa o reacción inesperada")

    if gaming_hits >= 2:
        score = min(100, score + 8)
        reasons.append("Reacción de gaming intensa")

    if excitement_hits >= 1:
        score = min(100, score + 5)
        reasons.append("Momento de alta emoción")

    # Existing emotion signal from breakdown
    if bd.get("humor", 0.0) >= 0.3:
        reasons.append("Humor detectado en el segmento")
    if bd.get("revelation", 0.0) >= 0.3:
        reasons.append("Revelación o descubrimiento")

    if score < 25 and has_transcript:
        warnings.append("Bajo contenido emocional — puede parecer plano")

    return round(score, 1), reasons, warnings


def _score_context(bd, seg_words, first_words, last_words, duration, has_transcript):
    reasons = []
    warnings = []

    if not has_transcript:
        return 50.0, ["Sin transcripción disponible"], []

    # Existing standalone score as base
    existing_standalone = bd.get("standalone", 0.5)
    llm_standalone = None
    llm_data = bd.get("llm_analysis", {}) or {}
    if llm_data:
        llm_standalone = llm_data.get("standalone_value", 50) / 100.0
    base = (existing_standalone * 0.4 + llm_standalone * 0.6) if llm_standalone else existing_standalone
    score = base * 100.0

    # Check if first word is a pronoun/connector (bad start)
    if seg_words:
        first_text = " ".join(w["word"] for w in seg_words[:5]).lower()
        is_bad_start = any(re.match(p, first_text) for p in BAD_START_PATTERNS)
        if is_bad_start:
            score = max(0, score - 20)
            warnings.append("El clip puede empezar en medio de una frase — revisa el punto de corte")
        else:
            # Check for good start signals
            if any(sig in first_words for sig in GOOD_START_SIGNALS):
                score = min(100, score + 10)
                reasons.append("Inicio claro y comprensible")

    # Check ending quality
    has_natural_end = any(last_words.rstrip().endswith(sig) for sig in [".", "!", "?"])
    if has_natural_end:
        score = min(100, score + 10)
        reasons.append("Final natural — la frase está completa")
    else:
        # Check if last word is mid-sentence
        if seg_words and not any(seg_words[-1]["word"].endswith(p) for p in [".", "!", "?", "…"]):
            if duration < 55:  # only flag if not hitting max duration
                score = max(0, score - 10)
                warnings.append("El clip puede terminar en medio de una frase")

    # Narrative completeness from LLM
    if llm_data:
        narrative = llm_data.get("narrative_completeness", 50) / 100.0
        score = score * 0.7 + narrative * 100 * 0.3
        if narrative >= 0.7:
            reasons.append("Arco narrativo completo")
        elif narrative < 0.35:
            warnings.append("Narrativa incompleta — el clip puede carecer de resolución")

    # Story structure bonus
    story = bd.get("story_structure", {})
    if isinstance(story, str):
        try:
            story = json.loads(story)
        except Exception:
            story = {}
    if story.get("has_setup") and story.get("has_payoff"):
        score = min(100, score + 10)
        reasons.append("Contiene planteamiento y desenlace")
    elif story.get("has_payoff"):
        score = min(100, score + 5)
        reasons.append("Tiene un desenlace claro")

    if score < 30:
        warnings.append("Contexto insuficiente — el espectador puede no entender el clip")

    return round(score, 1), reasons, warnings


def _score_engagement(bd, llm, seg_text, has_transcript):
    reasons = []

    if not has_transcript:
        return 40.0, []

    # Base from existing shareability and relatability
    shareability = bd.get("shareability", 0.4)
    relatability = bd.get("relatability", 0.0)
    conflict = bd.get("conflict", 0.0)
    base = (shareability * 0.5 + relatability * 0.3 + conflict * 0.2)
    score = base * 100.0

    # LLM shareability
    if llm:
        llm_share = llm.get("shareability", 50) / 100.0
        score = score * 0.4 + llm_share * 100 * 0.6

    # Streamer-specific engagement signals
    engagement_hits = sum(1 for sig in ENGAGEMENT_SIGNALS_ES if sig in seg_text)
    if engagement_hits >= 3:
        score = min(100, score + 15)
        reasons.append("Múltiples señales de interacción con el chat")
    elif engagement_hits >= 1:
        score = min(100, score + 7)
        reasons.append("Invita a la interacción del espectador")

    # Questions in general (direct to audience)
    question_count = seg_text.count("?") + seg_text.count("¿")
    if question_count >= 2:
        score = min(100, score + 8)
        reasons.append("Varias preguntas — activa comentarios")
    elif question_count == 1:
        score = min(100, score + 4)

    # Controversy boost
    if conflict >= 0.4:
        score = min(100, score + 8)
        reasons.append("Momento polémico o de conflicto — genera debate")

    # Humor as engagement
    if bd.get("humor", 0) >= 0.3:
        score = min(100, score + 6)
        reasons.append("Humor que invita a compartir")

    if score >= 70:
        reasons.append("Alto potencial de interacción")

    return round(score, 1), reasons


def _score_rhythm(bd, seg_words, duration, has_transcript):
    reasons = []
    warnings = []

    if not has_transcript or not seg_words:
        return 50.0, [], []

    # Words per second
    wps = len(seg_words) / duration
    if 1.8 <= wps <= 3.8:
        wps_score = 100.0
        reasons.append("Ritmo de conversación natural")
    elif wps < 1.8:
        wps_score = max(20, wps / 1.8 * 100)
        if wps < 1.0:
            warnings.append("Ritmo muy lento — posibles tiempos muertos")
    else:
        wps_score = max(50, 100 - (wps - 3.8) * 15)

    # Dead air (pause) analysis
    dead_air = bd.get("dead_air", 0.0) if "dead_air" in bd else None
    if dead_air is not None:
        if dead_air > 0.40:
            dead_score = 30.0
            warnings.append("Mucho silencio — hay pausas largas en el clip")
        elif dead_air > 0.25:
            dead_score = 60.0
        else:
            dead_score = 100.0
    else:
        dead_score = 70.0  # neutral when no data

    # Filler words penalty
    filler_hits = sum(1 for fw in RHYTHM_DEAD_TIME_SIGNALS
                      if fw in " ".join(wd["word"] for wd in seg_words).lower())
    filler_penalty = min(20, filler_hits * 3)

    # Retention score from existing analysis
    retention = bd.get("retention", 0.5)
    retention_score = retention * 100

    score = (wps_score * 0.35 + dead_score * 0.25 + retention_score * 0.40) - filler_penalty
    score = max(0, min(100, score))

    if score >= 70:
        reasons.append("Buena densidad y ritmo de contenido")

    return round(score, 1), reasons, warnings


def _score_quality(candidate, duration):
    reasons = []
    warnings = []

    audio_score = float(candidate.get("audio_score", 0.5) or 0.5)
    visual_score = float(candidate.get("visual_score", 0.5) or 0.5)

    score = (audio_score * 0.55 + visual_score * 0.45) * 100

    # Duration fit for Shorts
    if 20 <= duration <= 58:
        score = min(100, score + 10)
        reasons.append("Duración ideal para YouTube Shorts")
    elif duration < 15:
        score = max(0, score - 20)
        warnings.append("Clip muy corto para Shorts")
    elif duration > 58:
        score = max(0, score - 10)
        warnings.append("Clip largo — puede superar el límite de Shorts")

    if audio_score >= 0.7:
        reasons.append("Buena calidad de audio")
    elif audio_score < 0.3:
        warnings.append("Señal de audio débil")

    if visual_score >= 0.7:
        reasons.append("Buena calidad visual")

    return round(score, 1), reasons, warnings


def _score_originality(candidate, all_candidates):
    reasons = []
    warnings = []

    start = candidate.get("start_s", 0)
    end = candidate.get("end_s", 30)
    cid = candidate.get("id", "")

    if not all_candidates:
        return 80.0, ["Sin candidatos adicionales para comparar"], []

    # Check IoU overlap with other candidates
    max_overlap = 0.0
    for other in all_candidates:
        if other.get("id") == cid:
            continue
        # Skip archived/rejected candidates
        if other.get("status") in ("GROUPED_ALT", "REJECTED", "ARCHIVED"):
            continue
        o_start = other.get("start_s", 0)
        o_end = other.get("end_s", 30)
        intersection = max(0, min(end, o_end) - max(start, o_start))
        union = max(end, o_end) - min(start, o_start)
        iou = intersection / union if union > 0 else 0
        max_overlap = max(max_overlap, iou)

    if max_overlap >= 0.7:
        score = 30.0
        warnings.append("Alta superposición con otro candidato — posible duplicado")
    elif max_overlap >= 0.4:
        score = 55.0
        warnings.append("Leve superposición temporal con otro candidato")
    elif max_overlap >= 0.15:
        score = 80.0
        reasons.append("Segmento mayormente único")
    else:
        score = 100.0
        reasons.append("Momento único sin solapamiento")

    return round(score, 1), reasons, warnings


# ── Confidence computation ────────────────────────────────────────────────────

def _compute_confidence(has_transcript: bool, has_llm: bool, candidate: dict) -> float:
    """Estimate how confident the score is given available signals."""
    confidence = 0.5  # baseline

    if has_transcript:
        confidence += 0.25
    if has_llm:
        confidence += 0.15
    if float(candidate.get("audio_score", 0) or 0) > 0:
        confidence += 0.05
    if float(candidate.get("visual_score", 0) or 0) > 0:
        confidence += 0.05

    return round(min(1.0, confidence), 2)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_breakdown(candidate: dict) -> dict:
    bd = candidate.get("score_breakdown", {})
    if isinstance(bd, str):
        try:
            parsed = json.loads(bd)
            # Handle double-encoded JSON
            if isinstance(parsed, str):
                try:
                    return json.loads(parsed)
                except Exception:
                    return {}
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return bd if isinstance(bd, dict) else {}


def _validate_weights(w: dict) -> None:
    total = sum(w.values())
    if abs(total - 1.0) > 0.05:
        logger.warning("StreamerScorerV2: weights sum to %.3f, expected ~1.0", total)
