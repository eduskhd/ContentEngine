"""LLM-based transcript analysis via Claude API.

Analyzes candidate segments for viral potential, hook quality, and emotional resonance.
Batches multiple candidates per call to minimize cost and latency.
Results are persisted in candidates.score_breakdown['llm_analysis'] — skipped on retry.

Requires: ANTHROPIC_API_KEY environment variable.
Gracefully disabled if key absent, anthropic package missing, or API call fails.
Falls back to neutral scores (0.5 on each dimension) so the heuristic system carries the weight.
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_BATCH_SIZE = 8  # candidates per API call — balances latency vs cost

_SYSTEM_PROMPT = """You are a short-form video content analyst. You specialize in identifying moments from transcripts that would perform well as 30–60 second TikTok, YouTube Shorts, or Instagram Reels clips.

Analyze each transcript segment and return a JSON array. One object per segment, same order as input.

Each object must have EXACTLY these fields:
- viral_potential: integer 0–100 (overall viral ceiling — will strangers watch and share?)
- hook_quality: integer 0–100 (first-3-seconds magnetism — does the opening stop a scroll?)
- emotional_resonance: integer 0–100 (gut-level emotional impact — does it make viewers feel something?)
- shareability: integer 0–100 (will viewers forward this to a friend or repost?)
- standalone_value: integer 0–100 (does it make complete sense without watching the source video?)
- narrative_completeness: integer 0–100 (clear arc — setup → tension/conflict → resolution/payoff?)
- hook_type: exactly one of: "question" | "shock" | "story" | "revelation" | "humor" | "conflict" | "educational" | "relatable" | "transformation" | "other"
- reasons: array of 2–4 short strings (max 60 chars each) naming the specific signals that drove your score

Scoring guidance:
- 80–100: this would genuinely stop most scrollers; clear viral signal
- 60–79: strong potential, likely to get solid engagement
- 40–59: average; some interesting moments but no standout viral signal
- 20–39: weak; probably not compelling as a standalone clip
- 0–19: filler content; no viral signal

Respond ONLY with the raw JSON array. No markdown, no explanation, no preamble."""


def analyze_candidates_llm(
    candidates: list[dict],
    words: list[dict],
) -> dict[str, dict]:
    """Analyze candidates using LLM. Returns {candidate_id: score_dict}.

    candidates: list of candidate row dicts (from DB, including score_breakdown)
    words: full word-level transcript list [{word, start, end}, ...]

    Returns {} if LLM is unavailable (no key, no package, etc.).
    Returns neutral scores for any candidate where the API call fails.
    """
    if not candidates or not words:
        return {}

    api_key = _get_api_key()
    if not api_key:
        return {}

    results = {}
    to_analyze = []

    # Split into cached vs uncached
    for cand in candidates:
        cached = _extract_cached(cand)
        if cached:
            results[cand["id"]] = cached
        else:
            to_analyze.append(cand)

    if not to_analyze:
        return results

    # Build (id, text, start, end) tuples for uncached candidates
    segments = []
    for cand in to_analyze:
        text = _extract_text(words, cand["start_s"], cand["end_s"])
        if len(text.split()) >= 5:  # skip near-empty segments
            segments.append((cand["id"], text, cand["start_s"], cand["end_s"]))
        else:
            results[cand["id"]] = _neutral_scores()

    if not segments:
        return results

    # Process in batches
    for i in range(0, len(segments), _BATCH_SIZE):
        batch = segments[i : i + _BATCH_SIZE]
        try:
            batch_results = _call_api(batch, api_key)
            for cid, scores in batch_results.items():
                results[cid] = scores
                _persist_to_db(cid, scores)
        except Exception as exc:
            logger.warning("LLM batch %d failed: %s", i // _BATCH_SIZE, exc)
            for cid, *_ in batch:
                results[cid] = _neutral_scores()

    return results


# ── Internal helpers ───────────────────────────────────────────────────────────

def _extract_text(words: list[dict], start_s: float, end_s: float) -> str:
    w_in = [w for w in words if w["start"] >= start_s - 0.1 and w["end"] <= end_s + 0.1]
    return " ".join(w["word"] for w in w_in).strip()


def _extract_cached(cand: dict) -> Optional[dict]:
    """Pull previously stored LLM scores from score_breakdown."""
    bd = cand.get("score_breakdown", {})
    if isinstance(bd, str):
        try:
            bd = json.loads(bd)
        except Exception:
            return None
    llm = bd.get("llm_analysis")
    if isinstance(llm, dict) and "viral_potential" in llm:
        return llm
    return None


def _call_api(batch: list[tuple], api_key: str) -> dict[str, dict]:
    """Call Claude claude-haiku-4-5-20251001 for a batch and parse results."""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — LLM analysis disabled. Run: pip install anthropic")
        return {cid: _neutral_scores() for cid, *_ in batch}

    client = anthropic.Anthropic(api_key=api_key)

    user_parts = []
    for idx, (cid, text, start_s, end_s) in enumerate(batch):
        duration = round(end_s - start_s, 1)
        user_parts.append(f"Segment {idx + 1} ({duration}s):\n{text}")
    user_message = "\n\n---\n\n".join(user_parts)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

    results = {}
    for idx, (cid, *_) in enumerate(batch):
        if idx < len(parsed):
            results[cid] = _normalize(parsed[idx])
        else:
            results[cid] = _neutral_scores()
    return results


def _normalize(item: dict) -> dict:
    """Clamp and validate a single LLM response object."""
    def _int(v, default=50):
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            return default

    valid_types = {
        "question", "shock", "story", "revelation", "humor",
        "conflict", "educational", "relatable", "transformation", "other",
    }
    hook_type = str(item.get("hook_type", "other")).lower().strip()
    if hook_type not in valid_types:
        hook_type = "other"

    reasons = item.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = []
    reasons = [str(r)[:80].strip() for r in reasons[:4] if r]

    return {
        "viral_potential":        _int(item.get("viral_potential",        50)),
        "hook_quality":           _int(item.get("hook_quality",           50)),
        "emotional_resonance":    _int(item.get("emotional_resonance",    50)),
        "shareability":           _int(item.get("shareability",           50)),
        "standalone_value":       _int(item.get("standalone_value",       50)),
        "narrative_completeness": _int(item.get("narrative_completeness", 50)),
        "hook_type":              hook_type,
        "reasons":                reasons,
    }


def _neutral_scores() -> dict:
    return {
        "viral_potential": 50,
        "hook_quality": 50,
        "emotional_resonance": 50,
        "shareability": 50,
        "standalone_value": 50,
        "narrative_completeness": 50,
        "hook_type": "other",
        "reasons": [],
    }


def _get_api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    try:
        from engine.config import CONFIG
        return getattr(CONFIG, "anthropic_api_key", None) or None
    except Exception:
        return None


def _persist_to_db(candidate_id: str, scores: dict) -> None:
    """Merge LLM scores into candidates.score_breakdown without overwriting other data."""
    try:
        from engine import database as dbmod
        with dbmod.db() as conn:
            row = conn.execute(
                "SELECT score_breakdown FROM candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if not row:
                return
            bd = {}
            if row["score_breakdown"]:
                try:
                    bd = json.loads(row["score_breakdown"])
                except Exception:
                    bd = {}
            bd["llm_analysis"] = scores
            bd["llm_hook_type"] = scores["hook_type"]
            bd["llm_reasons"] = scores["reasons"]
            conn.execute(
                "UPDATE candidates SET score_breakdown=? WHERE id=?",
                (json.dumps(bd), candidate_id),
            )
    except Exception as exc:
        logger.debug("LLM persist failed for %s: %s", candidate_id[:8], exc)
