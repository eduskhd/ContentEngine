"""Clip metadata generator — editorial_v1 policy.

Produces publication-ready descriptions and hashtags for YouTube Shorts.

Priority:
  1. LLM (Claude Haiku) when ANTHROPIC_API_KEY is set — uses transcript as evidence
  2. Deterministic template — creator + topic + context, no transcript dump
  3. Minimal fallback — "Fragmento del stream de {creator}" when insufficient data

meta_version: "editorial_v1" for both LLM and deterministic paths.

Description format (stored in publications.caption — NO hashtags here):
    {1-2 sentences, Spanish, third person, 20-45 words, specific to this clip}

Full YouTube description (assembled by assemble_youtube_description()):
    {caption}

    Creador: {name}
    Vídeo original: {url}          ← only when available

    #Hashtag1 #Hashtag2 ...

Hashtag policy (editorial_v1):
  Order: creator → topic → category → #Shorts → #ContentEngine
  Max: 5. Never: #FYP #ParaTi #Viral #Trending #Twitch #Kick
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ── Policy version ─────────────────────────────────────────────────────────────

POLICY_VERSION = "editorial_v1"
MAX_HASHTAGS   = 5
_BRAND_TAG     = "#ContentEngine"
_SHORTS_TAG    = "#Shorts"

# ── Creator alias map ──────────────────────────────────────────────────────────
# Normalized creator name (lowercase, stripped) → canonical hashtag

_CREATOR_ALIASES: dict[str, str] = {
    "ibai":             "#Ibai",
    "ibai llanos":      "#Ibai",
    "auron":            "#Auronplay",
    "auronplay":        "#Auronplay",
    "rubius":           "#Rubius",
    "elrubius":         "#Rubius",
    "el rubius":        "#Rubius",
    "illojuan":         "#IlloJuan",
    "illo juan":        "#IlloJuan",
    "westcol":          "#Westcol",
    "pereira":          "#Peereira7",
    "peereira":         "#Peereira7",
    "peereira7":        "#Peereira7",
    "xbuyer":           "#Xbuyer",
    "bycalitos":        "#Bycalitos",
    "bycalitos_":       "#Bycalitos",
    "mrbeast":          "#MrBeast",
    "mr beast":         "#MrBeast",
    "blv":              "#Blv",
    "anita_rqp":        "#AnitaRQP",
    "anita rqp":        "#AnitaRQP",
    "thegregf":         "#TheGregf",
    "gregf":            "#TheGregf",
    "la sotanita":      "#LaSotanita",
    "sotanita":         "#LaSotanita",
    "luisito comunica": "#LuisitoComunica",
    "luisito":          "#LuisitoComunica",
    "crm carli":        "#CRMCarli",
    "carli":            "#CRMCarli",
    "drafteados":       "#Drafteados",
    "neymar":           "#Neymar",
}

# ── Topic keywords → hashtag ───────────────────────────────────────────────────
# Each entry: (list_of_keywords, hashtag)
# Keywords checked in transcript + source_title (case-insensitive)

_TOPIC_KEYWORDS: list[tuple[list[str], str]] = [
    (["among us", "among"],                          "#AmongUs"),
    (["minecraft"],                                  "#Minecraft"),
    (["mario kart", "mariokart"],                    "#MarioKart"),
    (["fortnite"],                                   "#Fortnite"),
    (["gta", "grand theft auto"],                    "#GTA"),
    (["star wars", "starwars"],                      "#StarWars"),
    (["robot", "robots", "robótica"],                "#Robot"),
    (["sons of the forest", "sons of forest"],       "#SonsOfTheForest"),
    (["rocket league"],                              "#RocketLeague"),
    (["league of legends", "league of legend"],      "#LeagueOfLegends"),
    (["call of duty", "warzone"],                    "#CallOfDuty"),
    (["valorant"],                                   "#Valorant"),
    (["apex legends", "apex"],                       "#ApexLegends"),
    (["counter-strike", "counter strike", "cs2", "csgo"], "#CS2"),
    (["the forest"],                                 "#TheForest"),
    (["velada", "velada del año"],                   "#VeladaDelAño"),
    (["fall guys"],                                  "#FallGuys"),
    (["stumble guys"],                               "#StumbleGuys"),
    (["lethal company"],                             "#LethalCompany"),
]

# ── Category keywords → hashtag ────────────────────────────────────────────────

_CATEGORY_KEYWORDS: list[tuple[list[str], str]] = [
    (["funny", "humor", "comedy", "gracioso", "risa", "reírse"], "#Humor"),
    (["gaming", "game", "jugando", "videojuego"],                 "#Gaming"),
    (["reaction", "reaccion", "reacción", "reacciona"],           "#Reacciones"),
]

# Topic tags that imply #Gaming — used as category fallback when #Clips would be uninformative
_GAMING_TOPIC_TAGS: frozenset[str] = frozenset({
    "#AmongUs", "#Minecraft", "#MarioKart", "#Fortnite", "#GTA",
    "#SonsOfTheForest", "#RocketLeague", "#LeagueOfLegends", "#CallOfDuty",
    "#Valorant", "#ApexLegends", "#CS2", "#TheForest", "#FallGuys",
    "#StumbleGuys", "#LethalCompany",
})

# ── Banned tags (stripped, lowercased) ────────────────────────────────────────

_BANNED_TAGS = {
    "fyp", "parati", "foryou", "viral", "trending", "twitch", "kick",
    "follow", "followformore", "explore",
}

# ── Generic caption patterns (for validation) ─────────────────────────────────

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
    "contenido generado",
    "clip generado",
    "no te lo vas a creer",
]

_GENERIC_TITLES = {
    "short", "untitled", "clip", "video", "short 1", "clip 1",
    "shorts", "clips", "untitled clip", "untitled video",
}

_GENERIC_TITLE_RE  = re.compile(r'^(clip|short|video|untitled)\s*\d*$', re.IGNORECASE)
_TEMPLATE_MARKER_RE = re.compile(r'(\{\{|\[\[|<[A-Z][A-Z_]{2,})')
_TIMESTAMP_RE      = re.compile(r'\b\d{2}:\d{2}:\d{2}\b')
_SRT_ARROW_RE      = re.compile(r'\d{2}:\d{2}:\d{2}[,\.]\d+ ?--?> ?\d{2}:\d{2}:\d{2}')

# ── Public API ─────────────────────────────────────────────────────────────────


def generate_clip_metadata(clip_id: str) -> dict:
    """Generate title, caption (editorial text), hashtags for a clip. Never raises.

    Returns:
        {
            "title":        str,
            "caption":      str,   # editorial text only — no hashtags, no "Creador:" line
            "hashtags":     list[str],  # with # prefix, per editorial_v1 policy
            "meta_version": str,
        }
    """
    from engine import database as db

    try:
        with db.db() as conn:
            row = conn.execute("""
                SELECT ca.virality_reasons, ca.virality_score, ca.start_s, ca.end_s,
                       cr.name  AS creator_name,
                       cr.handle AS creator_handle,
                       v.source_title, v.source_url, v.source_platform,
                       cs.title AS series_title,
                       cl.caption_data
                FROM candidates ca
                JOIN clips cl ON cl.candidate_id = ca.id
                LEFT JOIN videos v   ON v.id = ca.video_id
                LEFT JOIN creators cr ON cr.id = v.creator_id
                LEFT JOIN clip_series cs ON cs.id = ca.series_id
                WHERE cl.id = ?
            """, (clip_id,)).fetchone()
    except Exception as exc:
        logger.warning("generate_clip_metadata DB query failed for %s: %s", clip_id[:8], exc)
        return {"title": "", "caption": "", "hashtags": [], "meta_version": "error"}

    if not row:
        logger.warning("generate_clip_metadata: clip %s not found", clip_id[:8])
        return {"title": "", "caption": "", "hashtags": [], "meta_version": "error"}

    d = dict(row)

    try:
        reasons = json.loads(d.get("virality_reasons") or "[]")
    except Exception:
        reasons = []

    transcript   = _extract_transcript(d.get("caption_data"))
    creator_name = _clean_creator(d.get("creator_name"))
    creator_handle = _normalize_text(d.get("creator_handle") or "")
    source_title = _normalize_text(d.get("source_title") or "")
    series_title = _normalize_text(d.get("series_title") or "")
    start_s      = float(d.get("start_s") or 0)
    end_s        = float(d.get("end_s") or 0)
    duration     = round(end_s - start_s, 1) if end_s > start_s else 0

    # Detect topic and category from available evidence
    search_text = f"{transcript} {source_title} {series_title} {' '.join(reasons)}".lower()
    topic_tag    = _detect_topic(search_text)
    category_tag = _detect_category(search_text, reasons)

    # LLM path (overrides deterministic topic/category with LLM's judgment)
    if transcript and _llm_key():
        result = _llm_generate(
            transcript=transcript,
            creator_name=creator_name,
            source_title=source_title,
            reasons=reasons,
            duration=duration,
        )
        if result:
            topic_tag_llm    = result.get("topic_tag") or topic_tag
            category_tag_llm = result.get("category_tag") or category_tag
            hashtags = _build_hashtags(
                creator_name, creator_handle, topic_tag_llm, category_tag_llm
            )
            title = _det_title(transcript, creator_name, source_title, series_title)
            return {
                "title":        title,
                "caption":      result["description"],
                "hashtags":     hashtags,
                "meta_version": POLICY_VERSION,
            }

    # Deterministic path
    title    = _det_title(transcript, creator_name, source_title, series_title)
    caption  = _det_caption(creator_name, source_title, topic_tag, category_tag)
    hashtags = _build_hashtags(creator_name, creator_handle, topic_tag, category_tag)

    return {
        "title":        title,
        "caption":      caption,
        "hashtags":     hashtags,
        "meta_version": POLICY_VERSION,
    }


def assemble_youtube_description(
    caption:      str,
    hashtags:     list[str],
    creator_name: str | None = None,
    source_url:   str | None = None,
) -> str:
    """Build the full text for snippet.description.

    Format:
        {caption}

        Creador: {creator_name}
        Vídeo original: {source_url}

        #Hashtag1 #Hashtag2 ...

    Omits any block that has no data. Never adds placeholders.
    Truncates to 5000 UTF-8 bytes (YouTube limit).
    """
    parts: list[str] = []

    if caption and caption.strip():
        parts.append(caption.strip())

    meta_lines: list[str] = []
    if creator_name and creator_name.strip():
        meta_lines.append(f"Creador: {creator_name.strip()}")
    if source_url and source_url.strip():
        meta_lines.append(f"Vídeo original: {source_url.strip()}")
    if meta_lines:
        parts.append("\n".join(meta_lines))

    clean_tags = _dedupe_hashtags(hashtags or [])
    if clean_tags:
        parts.append(" ".join(clean_tags))

    text = "\n\n".join(parts)
    return _truncate_utf8(text, 5000)


def validate_metadata(title: str, caption: str) -> tuple[bool, str]:
    """Return (is_valid, error_reason). Empty string on success.

    Validates the editorial caption (NOT the assembled description).
    """
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

    # Reject SRT / timestamp patterns
    if _SRT_ARROW_RE.search(c):
        return False, "description contains SRT timestamp arrows"
    if len(_TIMESTAMP_RE.findall(c)) >= 2:
        return False, "description contains multiple timestamps (likely SRT)"

    # Reject transcript paste: long text with no sentence-ending punctuation
    if len(c) > 80:
        sentence_ends = len(re.findall(r'[.!?]+', c))
        if sentence_ends == 0:
            return False, "description has no sentence structure (likely raw transcript)"
        words = c.split()
        if len(words) / max(sentence_ends, 1) > 30:
            return False, "description appears to be a transcript paste (too many words per sentence)"

    return True, ""


def validate_hashtags(hashtags: list[str]) -> tuple[bool, str]:
    """Validate hashtag list per editorial_v1 policy."""
    if not isinstance(hashtags, list):
        return False, "hashtags must be a list"
    if len(hashtags) > MAX_HASHTAGS:
        return False, f"too many hashtags ({len(hashtags)} > {MAX_HASHTAGS})"
    seen: set[str] = set()
    for tag in hashtags:
        if not isinstance(tag, str):
            return False, f"hashtag is not a string: {tag!r}"
        if not tag.startswith("#"):
            return False, f"hashtag missing # prefix: {tag!r}"
        norm = tag.lstrip("#").lower()
        if not norm:
            return False, "empty hashtag"
        if norm in _BANNED_TAGS:
            return False, f"banned hashtag: {tag!r}"
        if norm in seen:
            return False, f"duplicate hashtag: {tag!r}"
        seen.add(norm)
    return True, ""


# ── Internal helpers ───────────────────────────────────────────────────────────


def _llm_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key if key else None


def _extract_transcript(caption_data_json: str | None) -> str:
    if not caption_data_json:
        return ""
    try:
        d = json.loads(caption_data_json)
        words = d.get("words") or []
        return " ".join(w.get("word", "") for w in words if w.get("word"))
    except Exception:
        return ""


def _clean_creator(name: str | None) -> str:
    if not name:
        return ""
    stripped = name.strip()
    if stripped.lower() in ("creator", "unknown", ""):
        return ""
    return stripped


def _normalize_text(text: str) -> str:
    return (text or "").replace("­", "").replace(" ", " ").replace("​", "").strip()


def _truncate_at_word(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _first_sentence(text: str) -> str:
    _filler = re.compile(
        r'^(um+|uh+|well|so|okay|ok|right|yeah|you know|like|i mean)[,.]?\s+',
        re.IGNORECASE,
    )
    cleaned = _filler.sub("", text).strip()
    m = re.search(r'[.!?]+(?:\s|$)', cleaned)
    if m:
        sentence = cleaned[:m.end()].strip()
        if len(sentence) >= 15:
            return sentence
    if len(cleaned) <= 80:
        return cleaned
    return cleaned[:80].rsplit(" ", 1)[0]


def _creator_alias(creator_name: str, creator_handle: str) -> str:
    """Return canonical hashtag for creator, or a derived one."""
    # Check alias map first (by name and by handle)
    for key in (creator_name.lower().strip(), creator_handle.lower().lstrip("#").strip()):
        if key and key in _CREATOR_ALIASES:
            return _CREATOR_ALIASES[key]
    # Use handle if it already has # prefix
    if creator_handle and creator_handle.startswith("#"):
        return creator_handle
    # Derive from name
    if creator_name:
        safe = re.sub(r"[^a-zA-Z0-9]", "", creator_name)
        if safe:
            return "#" + safe
    return ""


def _detect_topic(search_text: str) -> str:
    """Find first matching topic hashtag in search text."""
    for keywords, tag in _TOPIC_KEYWORDS:
        for kw in keywords:
            if kw in search_text:
                return tag
    return ""


def _detect_category(search_text: str, reasons: list[str]) -> str:
    """Find best category hashtag."""
    combined = search_text + " " + " ".join(r.lower() for r in reasons)
    for keywords, tag in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in combined:
                return tag
    return "#Clips"


def _build_hashtags(
    creator_name:   str,
    creator_handle: str,
    topic_tag:      str,
    category_tag:   str,
) -> list[str]:
    """Build final hashtag list per editorial_v1 policy.

    Order: creator → topic → category → #Shorts → #ContentEngine
    Max: MAX_HASHTAGS (5). Deduplicates case-insensitively.
    """
    candidates = []

    creator_tag = _creator_alias(creator_name, creator_handle)
    if creator_tag:
        candidates.append(creator_tag)

    if topic_tag:
        candidates.append(topic_tag)

    # Upgrade #Clips fallback to #Gaming when topic is a known game title
    if category_tag == "#Clips" and topic_tag in _GAMING_TOPIC_TAGS:
        category_tag = "#Gaming"

    # Only add category when it adds information:
    # - skip #Clips fallback when a specific topic is already present
    if category_tag and not (topic_tag and category_tag == "#Clips"):
        candidates.append(category_tag)

    candidates.append(_SHORTS_TAG)
    candidates.append(_BRAND_TAG)

    return _dedupe_hashtags(candidates)[:MAX_HASHTAGS]


def _dedupe_hashtags(tags: list[str]) -> list[str]:
    """Remove duplicates (case-insensitive) and banned tags. Preserve order."""
    seen: set[str] = set()
    result: list[str] = []
    for t in tags:
        if not isinstance(t, str) or not t.startswith("#"):
            continue
        norm = t.lstrip("#").lower().strip()
        if not norm or norm in seen or norm in _BANNED_TAGS:
            continue
        seen.add(norm)
        result.append(t)
    return result


def _det_title(transcript: str, creator: str, source_title: str, series_title: str) -> str:
    if transcript:
        sentence = _first_sentence(transcript)
        candidate = f"{creator}: {sentence}" if creator else sentence
        result = _truncate_at_word(candidate, 100)
        sentence_part = (
            result[len(creator) + 2:]
            if creator and result.startswith(creator + ": ")
            else result
        )
        if len(sentence_part.strip()) >= 15:
            return result

    if source_title:
        base = f"{creator}: {source_title}" if creator else source_title
        return _truncate_at_word(base, 100)

    if series_title:
        base = f"{creator}: {series_title}" if creator else series_title
        return _truncate_at_word(base, 100)

    return creator or ""


def _det_caption(
    creator_name: str,
    source_title: str,
    topic_tag:    str,
    category_tag: str,
) -> str:
    """Build editorial caption using structured template — no transcript dump."""
    # Map topic tag to readable Spanish noun
    _topic_nouns = {
        "#AmongUs":    "Among Us",
        "#Minecraft":  "Minecraft",
        "#MarioKart":  "Mario Kart",
        "#Fortnite":   "Fortnite",
        "#GTA":        "GTA",
        "#StarWars":   "Star Wars",
        "#Robot":      "robótica",
    }
    # Map category to adjective/phrase used in the no-topic template
    _category_adj = {
        "#Humor":      "de humor",
        "#Gaming":     "de gameplay",
        "#Reacciones": "de reacción",
        "#Clips":      "destacado",
    }

    creator     = creator_name or "El creador"
    topic       = _topic_nouns.get(topic_tag, "")
    category_adj = _category_adj.get(category_tag, "destacado")

    # Build context from source_title, removing creator name to avoid redundancy
    context = ""
    if source_title:
        ctx = re.sub(re.escape(creator_name or ""), "", source_title, flags=re.IGNORECASE).strip(" -|:")
        if len(ctx) > 5:
            context = ctx[:60]

    if topic:
        if context:
            caption = f"{creator} juega {topic} en un momento {category_adj}. Tomado de: {context}."
        else:
            caption = f"{creator} juega {topic} en un momento {category_adj} de su stream."
    else:
        if context:
            caption = f"Momento {category_adj} del stream de {creator} en '{context}'."
        else:
            caption = f"Fragmento del stream de {creator}."

    return caption


# ── LLM generation ─────────────────────────────────────────────────────────────

_LLM_SYSTEM = """\
Eres un editor de clips para redes sociales que escribe metadatos en español.

Tarea: describe un fragmento concreto de un stream para publicarlo en YouTube Shorts.

Devuelve SOLO JSON válido con estas claves:
{
  "description": "...",
  "topic_tag": "...",
  "category_tag": "..."
}

REGLAS PARA "description":
- Idioma: español natural
- Estilo: tercera persona, editorial, factual; no cites el diálogo
- Longitud: 1-2 frases, entre 20 y 45 palabras en total
- Contenido: creador, actividad/juego/tema y qué ocurre específicamente en ESTE fragmento
- Usa solo hechos que encuentres en los datos proporcionados; no inventes cifras, ganadores ni participantes
- Si no hay contexto suficiente, escribe: "Fragmento del stream de {creator}."
- PROHIBIDO: citas del diálogo, marcas de tiempo, texto SRT, "No te lo vas a creer",
  promesas de viralidad, emojis, insultos, datos inventados, relleno como "Clip generado"

REGLAS PARA "topic_tag":
- El hashtag del juego/evento si está claramente evidenciado
- Solo uno de: "#AmongUs" "#Minecraft" "#MarioKart" "#Fortnite" "#GTA" "#StarWars" "#Robot"
- Si no hay tema claro, devuelve ""

REGLAS PARA "category_tag":
- Solo uno de: "#Humor" (comedia clara), "#Gaming" (gameplay), "#Reacciones" (reacción), "#Clips" (general)
- Elige el más apropiado según el contenido"""


def _llm_generate(
    transcript:   str,
    creator_name: str,
    source_title: str,
    reasons:      list[str],
    duration:     float,
) -> dict | None:
    """Call Claude Haiku. Returns {"description", "topic_tag", "category_tag"} or None."""
    key = _llm_key()
    if not key:
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — LLM metadata disabled")
        return None

    user_msg = (
        f"CREATOR: {creator_name or 'unknown'}\n"
        f"SOURCE VIDEO: {source_title or 'unknown'}\n"
        f"DURATION: {duration}s\n"
        f"VIRALITY SIGNALS: {', '.join(reasons) or 'none'}\n"
        f"TRANSCRIPT (use as evidence only, do not copy):\n---\n{transcript[:600]}\n---"
    )

    try:
        client   = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_LLM_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

        result      = json.loads(raw)
        description = str(result.get("description") or "").strip()[:500]
        topic_tag   = str(result.get("topic_tag") or "").strip()
        category_tag = str(result.get("category_tag") or "").strip()

        # Validate description
        ok, reason = validate_metadata("placeholder", description)
        if not ok:
            logger.warning("LLM description failed validation (%s) — falling back", reason)
            return None

        # Validate topic/category tags — only allow known values
        known_topics = {t for _, t in _TOPIC_KEYWORDS}
        known_cats   = {"#Humor", "#Gaming", "#Reacciones", "#Clips"}
        if topic_tag not in known_topics:
            topic_tag = ""
        if category_tag not in known_cats:
            category_tag = "#Clips"

        return {"description": description, "topic_tag": topic_tag, "category_tag": category_tag}

    except json.JSONDecodeError as exc:
        logger.warning("LLM metadata: JSON parse failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("LLM metadata call failed: %s", exc)
        return None
