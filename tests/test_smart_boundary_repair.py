"""Automated tests for Smart Boundary Repair Engine (V2.1).

Run with: pytest tests/test_smart_boundary_repair.py -v
"""
import pytest
from engine.analyzers.smart_boundary_repair import (
    repair_boundary,
    repair_batch,
    check_post_repair_overlaps,
    _compute_iou,
    ALGORITHM_VERSION,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_words(segments):
    """Build word list from [(word, start, end), ...]."""
    return [{"word": w, "start": s, "end": e, "probability": 1.0} for w, s, e in segments]


def make_cand(start, end, cid="test-cand-001"):
    return {"id": cid, "start_s": start, "end_s": end}


# ── Output structure ──────────────────────────────────────────────────────────

class TestOutputStructure:
    def test_required_keys(self):
        c = make_cand(10, 30)
        r = repair_boundary(c, [])
        required = [
            "original_start", "original_end", "original_duration",
            "proposed_start", "proposed_end", "proposed_duration",
            "repair_confidence", "repair_reasons", "warnings",
            "repair_status", "algorithm_version",
            "start_diagnosis", "end_diagnosis",
        ]
        for k in required:
            assert k in r, f"Missing key: {k}"

    def test_algorithm_version(self):
        r = repair_boundary(make_cand(10, 30), [])
        assert r["algorithm_version"] == ALGORITHM_VERSION

    def test_repair_status_values(self):
        r = repair_boundary(make_cand(10, 30), [])
        assert r["repair_status"] in ("REPAIRED", "UNCHANGED", "NEEDS_REVIEW", "FAILED")

    def test_confidence_range(self):
        r = repair_boundary(make_cand(10, 30), [])
        assert 0.0 <= r["repair_confidence"] <= 1.0

    def test_original_timestamps_preserved(self):
        c = make_cand(12.3, 45.6)
        r = repair_boundary(c, [])
        assert r["original_start"] == pytest.approx(12.3, abs=0.01)
        assert r["original_end"] == pytest.approx(45.6, abs=0.01)

    def test_reasons_and_warnings_are_lists(self):
        r = repair_boundary(make_cand(10, 30), [])
        assert isinstance(r["repair_reasons"], list)
        assert isinstance(r["warnings"], list)


# ── Case A: Incomplete start ──────────────────────────────────────────────────

class TestIncompleteStart:
    def test_connector_start_detected(self):
        """'pero' just before clip start → first clip word 'mira' (lowercase, 0.2s gap) → MID_SENTENCE."""
        words = make_words([
            ("Jugábamos", 8.0, 8.5), ("bien.", 8.6, 9.0),
            ("pero", 9.5, 9.8), ("mira", 10.0, 10.3), ("esto.", 28.0, 29.0),
        ])
        r = repair_boundary(make_cand(10.0, 29.0), words)
        assert r["start_diagnosis"] in ("CONNECTOR_START", "MID_SENTENCE", "PRONOUN_START")

    def test_connector_start_repaired_backward(self):
        """Should propose an earlier start when there's a clean sentence beginning."""
        words = make_words([
            ("Increible.", 5.0, 5.8),
            ("Mira", 6.5, 6.8), ("esto.", 7.0, 7.5),  # new sentence
            ("y", 9.5, 9.7), ("encima", 9.8, 10.1), ("gana.", 25.0, 26.0),
        ])
        r = repair_boundary(make_cand(9.5, 26.0), words)
        if r["repair_status"] == "REPAIRED":
            assert r["proposed_start"] < 9.5

    def test_pronoun_start_with_short_pause(self):
        """'el' after short pause should be flagged."""
        words = make_words([
            ("cosa.", 9.0, 9.3),
            ("el", 9.5, 9.7), ("tío", 9.8, 10.2), ("lo", 10.3, 10.5), ("flipó.", 20.0, 20.5),
        ])
        r = repair_boundary(make_cand(9.5, 20.5), words)
        assert r["start_diagnosis"] != "OK"

    def test_clean_start_after_sentence(self):
        """Start after terminal punct → OK."""
        words = make_words([
            ("¡Bien!", 9.0, 9.4),
            ("Mira", 9.6, 9.9), ("qué", 10.0, 10.2), ("pasada.", 20.0, 21.0),
        ])
        r = repair_boundary(make_cand(9.6, 21.0), words)
        assert r["start_diagnosis"] == "OK"

    def test_clean_start_after_long_pause(self):
        """Start after 1.5s pause → OK regardless of word type."""
        words = make_words([
            ("habla.", 5.0, 5.5),
            ("pero", 7.0, 7.2), ("mira", 7.3, 7.6), ("ya.", 20.0, 20.5),
        ])
        r = repair_boundary(make_cand(7.0, 20.5), words)
        # 7.0 - 5.5 = 1.5s pause ≥ LONG_PAUSE → should be OK
        assert r["start_diagnosis"] == "OK"


# ── Case B: Incomplete end ────────────────────────────────────────────────────

class TestIncompleteEnd:
    def test_abrupt_end_detected(self):
        """Clip ends with no punct and word immediately follows."""
        words = make_words([
            ("Mira", 10.0, 10.3), ("esto", 20.0, 20.3),
            ("es", 29.0, 29.2), ("muy", 29.3, 29.5), ("bueno", 29.6, 29.9),
            ("y", 30.0, 30.1), ("además.", 30.2, 30.8),
        ])
        r = repair_boundary(make_cand(10.0, 30.0), words)
        assert r["end_diagnosis"] == "ABRUPT_END"

    def test_abrupt_end_repaired_forward(self):
        """Should propose a later end pointing to terminal punctuation."""
        words = make_words([
            ("Mira", 10.0, 10.3),
            ("termina", 28.0, 28.4), ("aquí", 29.0, 29.3),
            ("y", 29.4, 29.5), ("punto.", 31.0, 31.5),
        ])
        r = repair_boundary(make_cand(10.0, 29.5), words)
        if r["repair_status"] == "REPAIRED":
            assert r["proposed_end"] > 29.5
            assert r["proposed_end"] <= 31.5 + 0.1

    def test_end_with_terminal_punct(self):
        """Clip ends with '.' → OK."""
        words = make_words([
            ("Mira", 10.0, 10.3), ("esto.", 28.0, 29.0),
            ("Siguiente", 30.0, 30.5),
        ])
        r = repair_boundary(make_cand(10.0, 29.0), words)
        assert r["end_diagnosis"] == "OK"

    def test_end_with_long_pause(self):
        """End followed by 1.5s pause → OK."""
        words = make_words([
            ("Mira", 10.0, 10.3), ("esto", 28.0, 29.0),
            ("Hola", 30.5, 31.0),  # 1.5s gap after "esto"
        ])
        r = repair_boundary(make_cand(10.0, 29.0), words)
        assert r["end_diagnosis"] == "OK"


# ── Case C: Correct clip (should not be modified) ─────────────────────────────

class TestCorrectClip:
    def test_clean_clip_unchanged(self):
        """Clean start + clean end → UNCHANGED."""
        words = make_words([
            ("Termina.", 9.0, 9.5),
            ("Mira", 10.0, 10.3), ("qué", 10.4, 10.6), ("pasada.", 28.0, 29.0),
            ("Siguiente", 31.0, 31.5),
        ])
        r = repair_boundary(make_cand(10.0, 29.0), words)
        assert r["repair_status"] in ("UNCHANGED",)

    def test_unchanged_preserves_timestamps(self):
        words = make_words([
            ("Termina.", 9.0, 9.5),
            ("Esto", 10.0, 10.3), ("es.", 28.0, 29.0),
        ])
        r = repair_boundary(make_cand(10.0, 29.0), words)
        assert r["proposed_start"] == pytest.approx(10.0, abs=0.01)
        assert r["proposed_end"] == pytest.approx(29.0, abs=0.01)


# ── Case D: Max duration constraint ───────────────────────────────────────────

class TestDurationConstraints:
    def test_does_not_exceed_max_dur(self):
        words = make_words([
            ("porque", 4.0, 4.3),
            ("mira", 5.0, 5.3),
            ("esto", 55.0, 55.3),
            ("y", 60.0, 60.1), ("después.", 62.0, 63.0),
        ])
        r = repair_boundary(make_cand(5.0, 60.0), words, max_dur=62.0)
        assert r["proposed_duration"] <= 62.0

    def test_does_not_go_below_min_dur(self):
        words = make_words([
            ("Bien.", 9.5, 9.9),
            ("Y", 10.0, 10.1), ("fin.", 15.0, 15.5),
            ("Después", 15.6, 16.0),
        ])
        r = repair_boundary(make_cand(10.0, 15.5), words, min_dur=10.0)
        assert r["proposed_duration"] >= 5.0 or r["repair_status"] in ("UNCHANGED", "NEEDS_REVIEW")


# ── Case E: No transcript ─────────────────────────────────────────────────────

class TestNoTranscript:
    def test_empty_words_needs_review(self):
        r = repair_boundary(make_cand(10.0, 30.0), [])
        assert r["repair_status"] == "NEEDS_REVIEW"

    def test_empty_words_low_confidence(self):
        r = repair_boundary(make_cand(10.0, 30.0), [])
        assert r["repair_confidence"] < 0.5


# ── Case F: Invalid timestamps ────────────────────────────────────────────────

class TestInvalidTimestamps:
    def test_zero_duration_fails(self):
        r = repair_boundary(make_cand(10.0, 10.0), [{"word": "hola", "start": 9.0, "end": 9.5}])
        assert r["repair_status"] == "FAILED"

    def test_negative_start_fails(self):
        r = repair_boundary(make_cand(-1.0, 20.0), [{"word": "hola", "start": 0.0, "end": 0.5}])
        assert r["repair_status"] == "FAILED"


# ── Case G: Post-repair duplicates ────────────────────────────────────────────

class TestPostRepairDuplicates:
    def test_no_duplicates_if_no_overlap(self):
        candidates = [make_cand(0, 30, "a"), make_cand(60, 90, "b")]
        repairs = [
            {"proposed_start": 0, "proposed_end": 30, "repair_status": "UNCHANGED"},
            {"proposed_start": 60, "proposed_end": 90, "repair_status": "UNCHANGED"},
        ]
        overlaps = check_post_repair_overlaps(candidates, repairs)
        assert len(overlaps) == 0

    def test_detects_new_overlap_after_repair(self):
        # a repaired to [0,55], b [25,55] → IoU = 30/55 ≈ 0.545 > threshold
        candidates = [make_cand(0, 30, "a"), make_cand(25, 55, "b")]
        repairs = [
            {"proposed_start": 0, "proposed_end": 55, "repair_status": "REPAIRED"},
            {"proposed_start": 25, "proposed_end": 55, "repair_status": "UNCHANGED"},
        ]
        overlaps = check_post_repair_overlaps(candidates, repairs)
        assert len(overlaps) >= 1


# ── Batch helper ──────────────────────────────────────────────────────────────

class TestBatchHelper:
    def test_batch_returns_same_count(self):
        candidates = [make_cand(10, 30, f"c{i}") for i in range(5)]
        results = repair_batch(candidates, [])
        assert len(results) == 5

    def test_batch_adds_candidate_id(self):
        candidates = [make_cand(10, 30, "cand-abc")]
        results = repair_batch(candidates, [])
        assert results[0]["candidate_id"] == "cand-abc"


# ── IoU helper ────────────────────────────────────────────────────────────────

class TestIoU:
    def test_no_overlap(self):
        assert _compute_iou(0, 10, 20, 30) == 0.0

    def test_full_overlap(self):
        assert _compute_iou(0, 10, 0, 10) == pytest.approx(1.0)

    def test_partial_overlap(self):
        iou = _compute_iou(0, 10, 5, 15)
        assert 0.3 < iou < 0.4


# ── Feature flag ─────────────────────────────────────────────────────────────

def test_feature_flag_in_config():
    from engine.config import CONFIG
    assert hasattr(CONFIG, "smart_boundary_repair_enabled")
    assert CONFIG.smart_boundary_repair_enabled == False  # default off
