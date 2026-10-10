"""Tests for editorial_v1 metadata policy.

Covers the 10 scenarios from the encargo spec:
  a) Description: Spanish, third person, 20-45 words, no transcript paste
  b) Creator alias: normalized → canonical hashtag
  c) Game/topic: keyword detection → correct hashtag
  d) Category: signals → best category tag
  e) Hashtag count: never exceeds MAX_HASHTAGS (5)
  f) Banned tags: #FYP etc. never appear
  g) Deduplication: no repeated hashtag (case-insensitive)
  h) Validation: transcript paste → rejected
  i) Validation: SRT/timestamps → rejected
  j) assemble_youtube_description: correct format, no empty blocks
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.metadata_generator import (
    _creator_alias,
    _detect_topic,
    _detect_category,
    _build_hashtags,
    _dedupe_hashtags,
    _det_caption,
    assemble_youtube_description,
    validate_metadata,
    validate_hashtags,
    MAX_HASHTAGS,
    _BRAND_TAG,
    _SHORTS_TAG,
)

# ── helpers ────────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


# ── (a) Deterministic caption quality ─────────────────────────────────────────

def test_det_caption_topic():
    caption = _det_caption("Ibai", "Among Us con amigos", "#AmongUs", "#Gaming")
    assert "Ibai" in caption
    assert "Among Us" in caption
    wc = _word_count(caption)
    assert wc <= 50, f"Too long: {wc} words in {caption!r}"


def test_det_caption_no_topic():
    caption = _det_caption("Auronplay", "", "", "#Clips")
    assert "Auronplay" in caption or "Auron" in caption.lower()
    assert _word_count(caption) <= 50


def test_det_caption_minimal():
    caption = _det_caption("", "", "", "")
    assert isinstance(caption, str)
    assert len(caption) > 5


# ── (b) Creator alias ──────────────────────────────────────────────────────────

def test_creator_alias_ibai():
    assert _creator_alias("Ibai Llanos", "") == "#Ibai"
    assert _creator_alias("ibai", "") == "#Ibai"


def test_creator_alias_auron():
    assert _creator_alias("auronplay", "") == "#Auronplay"
    assert _creator_alias("Auron", "") == "#Auronplay"


def test_creator_alias_rubius():
    assert _creator_alias("El Rubius", "") == "#Rubius"


def test_creator_alias_illojuan():
    assert _creator_alias("IlloJuan", "") == "#IlloJuan"


def test_creator_alias_unknown_derives_from_name():
    tag = _creator_alias("MiCreator", "")
    assert tag.startswith("#")
    assert "MiCreator" in tag or "micreator" in tag.lower()


# ── (c) Topic detection ────────────────────────────────────────────────────────

def test_topic_among_us():
    assert _detect_topic("they played among us with friends") == "#AmongUs"


def test_topic_minecraft():
    assert _detect_topic("building a house in minecraft survival") == "#Minecraft"


def test_topic_gta():
    assert _detect_topic("driving around in gta with the crew") == "#GTA"


def test_topic_none():
    assert _detect_topic("random conversation about life") == ""


# ── (d) Category detection ─────────────────────────────────────────────────────

def test_category_humor():
    tag = _detect_category("everyone was laughing it was so gracioso", ["funny moment"])
    assert tag == "#Humor"


def test_category_gaming():
    tag = _detect_category("playing a videojuego", ["gaming clip"])
    assert tag == "#Gaming"


def test_category_default_clips():
    tag = _detect_category("random stream moment", [])
    assert tag == "#Clips"


# ── (e) Hashtag count cap ─────────────────────────────────────────────────────

def test_hashtags_max_5():
    tags = _build_hashtags("Ibai Llanos", "", "#AmongUs", "#Gaming")
    assert len(tags) <= MAX_HASHTAGS


def test_hashtags_always_has_brand_and_shorts():
    tags = _build_hashtags("", "", "", "")
    assert _BRAND_TAG in tags
    assert _SHORTS_TAG in tags


# ── (f) Banned tags ────────────────────────────────────────────────────────────

def test_no_banned_tags():
    banned = ["#FYP", "#ParaTi", "#Viral", "#Trending", "#Twitch", "#Kick"]
    for banned_tag in banned:
        result = _dedupe_hashtags([banned_tag, "#Ibai", _SHORTS_TAG, _BRAND_TAG])
        assert banned_tag not in result, f"{banned_tag} should have been filtered out"


# ── (g) Deduplication ─────────────────────────────────────────────────────────

def test_dedup_case_insensitive():
    tags = _dedupe_hashtags(["#Ibai", "#ibai", "#IBAI", _SHORTS_TAG])
    ibai_count = sum(1 for t in tags if t.lower() == "#ibai")
    assert ibai_count == 1, f"Duplicate #Ibai found: {tags}"


def test_dedup_brand_not_doubled():
    tags = _build_hashtags("", "", "", "")
    brand_count = sum(1 for t in tags if t.lower() == _BRAND_TAG.lower())
    assert brand_count == 1


# ── (h) Validate: transcript paste ────────────────────────────────────────────

def test_reject_transcript_paste():
    transcript = (
        "yeah so basically what happened is um I went to the store and then "
        "like I saw this thing and I was like wait what is going on with that "
        "because it was really weird and my friend told me that this is normal but"
    )
    ok, reason = validate_metadata("My Title", transcript)
    assert not ok, f"Expected rejection, got ok=True. Reason: {reason}"


def test_accept_valid_editorial():
    ok, _ = validate_metadata(
        "Ibai y sus amigos en Among Us",
        "Ibai Llanos lidera una partida de Among Us con sus amigos en un stream especial."
    )
    assert ok


# ── (i) Validate: SRT / timestamps ────────────────────────────────────────────

def test_reject_srt_timestamps():
    srt_caption = "00:00:01,500 --> 00:00:05,200 Hola amigos bienvenidos"
    ok, reason = validate_metadata("Title", srt_caption)
    assert not ok
    assert "timestamp" in reason.lower() or "srt" in reason.lower()


def test_reject_multiple_timestamps():
    ts_caption = "At 00:01:22 he says this. Then at 00:02:45 something else happens."
    ok, reason = validate_metadata("Title", ts_caption)
    assert not ok


# ── (j) assemble_youtube_description ─────────────────────────────────────────

def test_assemble_full():
    result = assemble_youtube_description(
        caption="Ibai juega Among Us con sus amigos en una partida épica.",
        hashtags=["#Ibai", "#AmongUs", "#Humor", "#Shorts", "#ContentEngine"],
        creator_name="Ibai Llanos",
        source_url="https://www.youtube.com/watch?v=abc123",
    )
    assert "Ibai juega" in result
    assert "Creador: Ibai Llanos" in result
    assert "Vídeo original: https://www.youtube.com/watch?v=abc123" in result
    assert "#Ibai" in result
    assert "#ContentEngine" in result


def test_assemble_no_url():
    result = assemble_youtube_description(
        caption="Fragmento del stream.",
        hashtags=["#Shorts"],
        creator_name="Rubius",
        source_url=None,
    )
    assert "Creador: Rubius" in result
    assert "Vídeo original" not in result


def test_assemble_no_creator():
    result = assemble_youtube_description(
        caption="Un momento divertido.",
        hashtags=["#Clips"],
        creator_name=None,
        source_url=None,
    )
    assert "Creador:" not in result
    assert "#Clips" in result


def test_assemble_empty_fields_no_placeholders():
    result = assemble_youtube_description("", [], None, None)
    assert "{{" not in result
    assert "[[" not in result
    assert result == "" or result.strip() == ""


def test_assemble_byte_limit():
    long_caption = "A" * 3000
    long_url = "https://example.com/" + "x" * 1000
    hashtags = ["#" + "H" * 40 for _ in range(5)]
    result = assemble_youtube_description(long_caption, hashtags, "Creator", long_url)
    assert len(result.encode("utf-8")) <= 5000


def test_validate_hashtags_no_banned():
    ok, reason = validate_hashtags(["#Ibai", "#Shorts", "#ContentEngine"])
    assert ok, reason


def test_validate_hashtags_rejects_fyp():
    ok, reason = validate_hashtags(["#FYP"])
    assert not ok
    assert "banned" in reason.lower()


def test_validate_hashtags_too_many():
    ok, reason = validate_hashtags(["#A", "#B", "#C", "#D", "#E", "#F"])
    assert not ok
    assert "too many" in reason.lower()


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import inspect, traceback
    fns = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {passed+failed}")
    sys.exit(1 if failed else 0)
