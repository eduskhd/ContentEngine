"""
Extract and group caption words for a specific clip window.

All timestamps in the returned data are normalized to clip-start = 0.0.
"""
from engine.config import CONFIG

_BREAK_CHARS = frozenset(".,!?;:")


def extract_clip_words(
    all_words: list[dict],
    clip_start: float,
    clip_end: float,
) -> list[dict]:
    """
    Return words whose timing overlaps [clip_start, clip_end].
    Timestamps are normalized so clip_start → 0.0.
    """
    clip_dur = clip_end - clip_start
    min_confidence = CONFIG.caption_min_word_confidence
    result = []
    for w in all_words:
        ws = float(w.get("start", 0))
        we = float(w.get("end", 0))
        if we < clip_start - 0.15 or ws > clip_end + 0.15:
            continue
        text = w.get("word", "").strip()
        if not text:
            continue
        # Drop low-confidence transcription guesses from captions
        if float(w.get("probability", 1.0)) < min_confidence:
            continue
        result.append({
            "word": text,
            "start": round(max(0.0, ws - clip_start), 3),
            "end": round(min(clip_dur, we - clip_start), 3),
            "probability": float(w.get("probability", 1.0)),
        })
    return result


def group_words(words: list[dict], max_words: int = 4) -> list[dict]:
    """
    Group words into caption segments of at most max_words.
    Breaks on punctuation when possible to improve readability.
    Returns: [{words, start, end, text}, ...]
    """
    if not words:
        return []

    groups: list[dict] = []
    i = 0
    while i < len(words):
        chunk = words[i: i + max_words]
        if not chunk:
            break

        # Try to find a natural break within the chunk (word ends with punctuation)
        split_at = len(chunk)
        for j, w in enumerate(chunk):
            if w["word"].rstrip()[-1:] in _BREAK_CHARS:
                split_at = j + 1
                break

        actual = words[i: i + split_at]
        groups.append({
            "words": actual,
            "start": actual[0]["start"],
            "end": actual[-1]["end"],
            "text": " ".join(w["word"] for w in actual),
        })
        i += split_at

    return groups
