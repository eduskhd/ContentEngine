"""Clip metadata generator: title, caption, hashtags from transcript + creator context.

Priority:
  1. LLM (Claude Haiku) when ANTHROPIC_API_KEY is set — uses transcript as data
  2. Deterministic — first sentence(s) from transcript, creator, source_title
  3. Empty strings — when insufficient data; caller shows "Completar"

meta_version values: "llm_v1" | "deterministic_v1" | "error"
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_FILLER_WORDS = re.compile(
    r'^(um+|uh+|well|so|okay|ok|right|yeah|you know|like|i mean)[,.]?\s+',
    re.IGNORECASE,
)

_GENERIC_TITLES = {
    "short", "untitled", "clip", "video", "short 1", "clip 1",
    "shorts", "clips", "untitled clip", "untitled video",
}

_GENERIC_TITLE_RE = re.compile(r'^(clip|short|video|untitled)\s*\d*$', re.IGNORECASE)

_TEMPLATE_MARKER_RE = re.compile(r'(\{\{|\[\[|<[A-Z][A-Z_]{2,})')

_GENERIC_CAPTIONS = [
    "follow for more",
    "this clip is insane",
    "clip of the day",
    "this one got me",
    "absolutely wild",
    "you need to see this",
    "peak content",
    "this moment hit different",
    "the reaction was priceless",
    "this had the whole room",
    "best moment of the stream",
    "this is why we watch",
    "clip of the year",
    "this clip is going viral",
    "nobody saw this coming",
    "wait for the reaction",
    "this caught everyone off guard",
    "the moment everything changed",
    "things escalated fast",
    "the reveal at the end",
]

_REASON_HASHTAG_MAP = {
    "funny": "#humor",
    "humor": "#humor",
    "comedy": "#humor",
    "conflict": "#drama",
    "argument": "#drama",
    "drama": "#drama",
    "educational": "#education",
    "educational content": "#education",
    "reaction": "#reaction",
    "reaccion": "#reaccion",
    "emotional": "#emotional",
    "emotion": "#emotional",
    "revelation": "#revelation",
    "reveal": "#revelation",
    "transformation": "#transformation",
    "story": "#storytelling",
    "narrative": "#storytelling",
}

# ── Public API ────────────────────────────────────────────────────────────────

def generate_clip_metadata(clip_id: str) -> dict:
    """Generate title, caption, hashtags for a clip. Never raises."""
    from engine import database as db

    try:
        with db.db() as conn:
            row = conn.execute("""
                SELECT ca.virality_reasons, ca.virality_score, ca.start_s, ca.end_s,
                       cr.name as creator_name, cr.handle as creator_handle,
                       v.source_title, v.source_platform,
                       cs.title as series_title,
                       cl.caption_data
                FROM candidates ca
                JOIN clips cl ON cl.candidate_id = ca.id
                LEFT JOIN videos v ON ca.video_id = v.id
                LEFT JOIN creators cr ON v.creator_id = cr.id
                LEFT JOIN clip_series cs ON ca.series_id = cs.id
                WHERE cl.id=?
            """, (clip_id,)).fetchone()
    except Exception as exc:
        logger.warning("generate_clip_metadata DB query failed for %s: %s", clip_id[:8], exc)
        return {"title": "", "caption": "", "hashtags": [], "meta_version": "error"}

    if not row:
        logger.warning("generate_clip_metadata: clip %s not found", clip_id[:8])
        return {"title": "", "caption": "", "hashtags": [], "meta_version": "error"}

    d = dict(row)

    # Parse virality_reasons
    try:
        reasons = json.loads(d.get("virality_reasons") or "[]")
    except Exception:
        reasons = []

    # Extract transcript text from caption_data
    transcript = _extract_transcript(d.get("caption_data"))

    creator_name = _clean_creator(d.get("creator_name"))
    creator_handle = _normalize_text(d.get("creator_handle") or "")
    source_title = _normalize_text(d.get("source_title") or "")
    series_title = _normalize_text(d.get("series_title") or "")
    virality_score = float(d.get("virality_score") or 0)
    start_s = float(d.get("start_s") or 0)
    end_s = float(d.get("end_s") or 0)
    duration = round(end_s - start_s, 1) if end_s > start_s else 0

    # Try LLM path first
    if transcript and _llm_key():
        result = _llm_generate(
            transcript=transcript,
            creator_name=creator_name,
            source_title=source_title,
            reasons=reasons,
            duration=duration,
        )
        if result:
            hashtags = _build_hashtags(reasons, creator_name, creator_handle, d.get("source_platform"))
            return {
                "title":       result["title"],
                "caption":     result["description"],
                "hashtags":    hashtags,
                "meta_version": "llm_v1",
            }

    # Deterministic fallback
    title   = _det_title(transcript, creator_name, source_title, series_title)
    caption = _det_caption(transcript, creator_name, source_title)
    hashtags = _build_hashtags(reasons, creator_name, creator_handle, d.get("source_platform"))

    return {
        "title":        title,
        "caption":      caption,
        "hashtags":     hashtags,
        "meta_version": "deterministic_v1",
    }


def validate_metadata(title: str, caption: str) -> tuple[bool, str]:
    """Return (is_valid, error_reason). Empty reason string on success."""
    t = (title or "").strip()
    c = (caption or "").strip()

    if not t:
        return False, "title is empty"
    if t.lower() in _GENERIC_TITLES:
        return False, f"title is a generic placeholder: {t!r}"
    if _GENERIC_TITLE_RE.match(t):
        return False, f"title matches generic pattern: {t!r}"
    if _TEMPLATE_MARKER_RE.search(t):
        return False, "title contains unfilled template markers"

    if not c:
        return False, "description is empty"
    c_lower = c.lower()
    for pattern in _GENERIC_CAPTIONS:
        if pattern in c_lower:
            return False, f"description contains generic filler: {pattern!r}"
    if _TEMPLATE_MARKER_RE.search(c):
        return False, "description contains unfilled template markers"

    return True, ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _llm_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key if key else None


def _extract_transcript(caption_data_json: str | None) -> str:
    """Return raw transcript text from caption_data JSON, or empty string."""
    if not caption_data_json:
        return ""
    try:
        d = json.loads(caption_data_json)
        words = d.get("words") or []
        return " ".join(w.get("word", "") for w in words if w.get("word"))
    except Exception:
        return ""


def _clean_creator(name: str | None) -> str:
    """Return creator name, or empty string if unknown/generic."""
    if not name:
        return ""
    stripped = name.strip()
    if stripped.lower() in ("creator", "unknown", ""):
        return ""
    return stripped


def _first_sentence(text: str) -> str:
    """Extract first sentence from text, stripping leading filler."""
    # Strip leading filler words
    cleaned = _FILLER_WORDS.sub("", text).strip()
    # Find first sentence-ending punctuation followed by a space or end
    m = re.search(r'[.!?]+(?:\s|$)', cleaned)
    if m:
        sentence = cleaned[:m.end()].strip()
        if len(sentence) >= 15:
            return sentence
    # No sentence-ending found or too short — take up to 80 chars at word boundary
    if len(cleaned) <= 80:
        return cleaned
    cut = cleaned[:80].rsplit(" ", 1)[0]
    return cut


def _normalize_text(text: str) -> str:
    """Strip Unicode control characters that corrupt titles (soft hyphens, non-breaking spaces)."""
    return text.replace("­", "").replace(" ", " ").replace("​", "").strip()


def _truncate_at_word(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")


def _det_title(transcript: str, creator: str, source_title: str, series_title: str) -> str:
    # Transcript is the most specific — use it first
    if transcript:
        sentence = _first_sentence(transcript)
        if creator:
            candidate = f"{creator}: {sentence}"
        else:
            candidate = sentence
        result = _truncate_at_word(candidate, 100)
        # Accept if the sentence part is meaningful (>=15 chars after removing creator prefix)
        sentence_part = result[len(creator) + 2:] if creator and result.startswith(creator + ": ") else result
        if len(sentence_part.strip()) >= 15:
            return result

    # Fall back to source_title (video title is more descriptive than generic series type)
    if source_title:
        base = f"{creator}: {source_title}" if creator else source_title
        return _truncate_at_word(base, 100)

    # Last resort: series title (often too generic, e.g. "Emotional Story")
    if series_title:
        base = f"{creator}: {series_title}" if creator else series_title
        return _truncate_at_word(base, 100)

    return ""


def _det_caption(transcript: str, creator: str, source_title: str) -> str:
    parts = []

    if transcript:
        excerpt = _truncate_at_word(transcript, 240)
        parts.append(excerpt)

    if creator:
        parts.append(f"Creator: {creator}.")

    if source_title and source_title not in (creator, ""):
        parts.append(f"From: {source_title}.")

    return "\n".join(parts)


def _build_hashtags(
    reasons: list[str],
    creator: str,
    creator_handle: str,
    platform: str | None,
) -> list[str]:
    tags: list[str] = []

    # Reason-based tags (max 2)
    reasons_lower = " ".join(r.lower() for r in reasons)
    for keyword, tag in _REASON_HASHTAG_MAP.items():
        if keyword in reasons_lower and tag not in tags:
            tags.append(tag)
        if len(tags) >= 2:
            break

    # Creator tag
    if creator_handle and creator_handle.startswith("#"):
        ctag = creator_handle
    elif creator and len(creator) <= 20:
        ctag = "#" + re.sub(r"[^a-zA-Z0-9]", "", creator)
    else:
        ctag = ""
    if ctag and ctag not in tags:
        tags.append(ctag)

    # Deduplicate and cap at 4 (no generic viral tags)
    seen, result = set(), []
    for t in tags:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            result.append(t)
    return result[:4]


# ── LLM generation ────────────────────────────────────────────────────────────

_LLM_SYSTEM = """You are a metadata generator for short-form video clips. Generate a specific title and description for this clip.
Output ONLY valid JSON with exactly these keys: {"title": "...", "description": "..."}

Rules for title (max 100 chars):
- Describe the exact moment, idea, or action in THIS clip
- Include the creator name naturally when it fits and is known
- Never use filler phrases: "This clip is insane", "Wait for the reaction", "Nobody saw this coming", "This moment hit different", "Clip of the day", "This one got me", etc.
- Use the language of the content

Rules for description (max 500 chars):
- 1-2 sentences about what specifically happens in this clip
- Add "Creator: [name]" on a new line when the creator is known and not "unknown"
- No invented claims, no exaggerations, no generic follow CTAs
- Use the language of the content"""


def _llm_generate(
    transcript: str,
    creator_name: str,
    source_title: str,
    reasons: list[str],
    duration: float,
) -> dict | None:
    """Call Claude Haiku. Returns {"title": str, "description": str} or None on failure."""
    key = _llm_key()
    if not key:
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — LLM metadata disabled")
        return None

    transcript_excerpt = transcript[:600]
    user_msg = (
        f"CREATOR: {creator_name or 'unknown'}\n"
        f"SOURCE VIDEO: {source_title or 'unknown'}\n"
        f"DURATION: {duration}s\n"
        f"VIRALITY SIGNALS: {', '.join(reasons) or 'none'}\n"
        f"TRANSCRIPT:\n---\n{transcript_excerpt}\n---"
    )

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_LLM_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        result = json.loads(raw)
        title = str(result.get("title") or "").strip()[:100]
        description = str(result.get("description") or "").strip()[:5000]

        # Validate LLM output
        ok, reason = validate_metadata(title, description)
        if not ok:
            logger.warning("LLM metadata failed validation (%s) — falling back", reason)
            return None

        return {"title": title, "description": description}

    except json.JSONDecodeError as exc:
        logger.warning("LLM metadata: JSON parse failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("LLM metadata call failed: %s", exc)
        return None
