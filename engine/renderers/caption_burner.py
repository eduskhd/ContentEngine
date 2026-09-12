"""
Caption burn-in pipeline step.

Extracts word-level data per clip, stores it in DB, then burns ASS captions
into the rendered video. DB connection is closed before running ffmpeg to
avoid holding the write lock during long encode operations.
"""
import json
from engine import database as db
from engine.captions.extractor import extract_clip_words
from engine.captions.presets import default_settings
from engine.captions.renderer import burn_captions_ass


def burn_captions(job_id: str, clip_ids: list[str], words: list[dict]) -> list[str]:
    """
    For each clip:
      1. Read clip metadata from DB.
      2. Extract words for the clip's time window (normalized timestamps).
      3. Save caption_data + default caption_settings to DB.
      4. Burn ASS captions into the reframed video (connection closed first).
      5. Update clip.captioned_path in DB.

    Returns list of clip IDs that now have a captioned file.
    """
    captioned = []

    for clip_id in clip_ids:
        # ── 1. Read metadata (short lock) ──────────────────────────────────
        with db.db() as conn:
            row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
            cand = conn.execute(
                "SELECT * FROM candidates WHERE id=?", (row["candidate_id"],)
            ).fetchone() if row else None

        if not row or not cand or not row["output_path"]:
            continue

        start_s   = float(cand["start_s"])
        end_s     = float(cand["end_s"])
        clip_path = row["output_path"]
        w         = row["width"] or 1080
        h         = row["height"] or 1920

        # ── 2. Extract + normalize timestamps ──────────────────────��───────
        clip_words = extract_clip_words(words, start_s, end_s)

        caption_data = {
            "words":      clip_words,
            "has_audio":  len(clip_words) > 0,
            "clip_start": start_s,
            "clip_end":   end_s,
        }
        settings = dict(default_settings())

        # ── 3. Save to DB (short lock) ─────────────────────────────────────���
        with db.db() as conn:
            conn.execute(
                "UPDATE clips SET caption_data=?, caption_settings=? WHERE id=?",
                (json.dumps(caption_data), json.dumps(settings), clip_id),
            )

        # ── 4. Run ffmpeg — NO DB connection held ───────────────────────────
        out_path = clip_path.replace(".mp4", "_captioned.mp4")
        success  = burn_captions_ass(clip_path, out_path, clip_words, settings, w, h)

        # ── 5. Update captioned_path (short lock) ───────────────────────────
        if success:
            with db.db() as conn:
                conn.execute(
                    "UPDATE clips SET captioned_path=? WHERE id=?", (out_path, clip_id)
                )
            captioned.append(clip_id)

    return captioned
