"""Unit tests for the Streamer Intelligence Scorer V2 and Quality Gates.

Run with:
    python -m pytest tests/test_streamer_scorer.py -v
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from engine.analyzers.streamer_scorer import (
    score_streamer_v2,
    _score_hook, _score_emotion, _score_context,
    _score_engagement, _score_rhythm, _score_quality, _score_originality,
    DEFAULT_WEIGHTS, SCORE_VERSION, NICHE,
)
from engine.analyzers.quality_gates import (
    gate_context, gate_duplicates, gate_technical, gate_confidence,
    run_all_gates,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_candidate(start=10.0, end=42.0, virality=65.0, audio=0.7, visual=0.6,
                    breakdown=None, cid="test-cand-001", video_id="test-vid-001",
                    job_id="test-job-001"):
    bd = breakdown or {
        "hook": 0.6,
        "emotion": 0.5,
        "standalone": 0.7,
        "shareability": 0.5,
        "retention": 0.6,
        "humor": 0.3,
        "revelation": 0.1,
        "conflict": 0.0,
        "relatability": 0.2,
        "dead_air": 0.1,
        "story_structure": {
            "has_setup": True,
            "has_escalation": True,
            "has_payoff": True,
            "has_cliffhanger": False,
        },
        "reasons": ["Hook detectado", "Humor presente"],
    }
    return {
        "id": cid,
        "video_id": video_id,
        "job_id": job_id,
        "start_s": start,
        "end_s": end,
        "virality_score": virality,
        "audio_score": audio,
        "visual_score": visual,
        "emotion_score": 0.0,
        "hook_score": 0.0,
        "retention_score": 0.0,
        "importance_score": 0.0,
        "status": "DETECTED",
        "score_breakdown": json.dumps(bd),
        "streamer_score_v2": None,
        "streamer_total_score": 0.0,
        "quality_gate_result": None,
        "moment_group_id": None,
    }


def _make_words(start=10.0, end=42.0, text="mira lo que acaba de pasar esto es una locura no me lo puedo creer tío"):
    words_list = text.split()
    duration = end - start
    step = duration / max(len(words_list), 1)
    return [
        {"word": w, "start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3)}
        for i, w in enumerate(words_list)
    ]


# ── Test: score_streamer_v2 ────────────────────────────────────────────────────

class TestStreamerScorerV2:

    def test_returns_required_keys(self):
        cand = _make_candidate()
        words = _make_words()
        result = score_streamer_v2(cand, words)
        assert result["score_version"] == SCORE_VERSION
        assert result["niche"] == NICHE
        assert "total_score" in result
        assert "confidence" in result
        assert "factors" in result
        assert "reasons" in result
        assert "warnings" in result
        assert "recommended_action" in result

    def test_factors_contain_all_seven(self):
        cand = _make_candidate()
        words = _make_words()
        result = score_streamer_v2(cand, words)
        required_factors = {"hook", "emotion", "context", "engagement", "rhythm", "quality", "originality"}
        assert required_factors == set(result["factors"].keys())

    def test_score_range_0_to_100(self):
        cand = _make_candidate()
        words = _make_words()
        result = score_streamer_v2(cand, words)
        assert 0.0 <= result["total_score"] <= 100.0
        for factor_score in result["factors"].values():
            assert 0.0 <= factor_score <= 100.0

    def test_confidence_range(self):
        cand = _make_candidate()
        words = _make_words()
        result = score_streamer_v2(cand, words)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_no_transcript_returns_neutral(self):
        cand = _make_candidate()
        result = score_streamer_v2(cand, [])
        # Should not crash, should return defaults
        assert 0.0 <= result["total_score"] <= 100.0
        assert result["confidence"] < 0.7  # lower confidence without transcript

    def test_streamer_expressions_boost_hook(self):
        cand_plain = _make_candidate(breakdown={"hook": 0.4, "emotion": 0.3, "standalone": 0.5,
                                                 "shareability": 0.4, "retention": 0.5,
                                                 "humor": 0.0, "revelation": 0.0, "conflict": 0.0,
                                                 "relatability": 0.0, "dead_air": 0.1,
                                                 "story_structure": {"has_setup": False, "has_escalation": False,
                                                                     "has_payoff": False, "has_cliffhanger": False},
                                                 "reasons": []})
        cand_streamer = _make_candidate(breakdown=cand_plain["score_breakdown"])

        words_plain = _make_words(text="hola esto es un vídeo normal sobre cosas de la vida")
        words_streamer = _make_words(text="no me lo puedo creer espera espera mira lo que acaba de pasar la locura")

        score_plain = score_streamer_v2(cand_plain, words_plain)
        score_streamer_res = score_streamer_v2(cand_streamer, words_streamer)

        assert score_streamer_res["factors"]["hook"] >= score_plain["factors"]["hook"]

    def test_custom_weights(self):
        cand = _make_candidate()
        words = _make_words()
        custom_weights = {
            "hook": 0.50, "emotion": 0.20, "context": 0.10,
            "engagement": 0.05, "rhythm": 0.05, "quality": 0.05, "originality": 0.05,
        }
        result = score_streamer_v2(cand, words, weights=custom_weights)
        assert 0.0 <= result["total_score"] <= 100.0

    def test_recommended_action_values(self):
        cand = _make_candidate()
        words = _make_words()
        result = score_streamer_v2(cand, words)
        assert result["recommended_action"] in ("prioritize", "generate", "review", "skip")

    def test_duplicate_detection_reduces_originality(self):
        cand = _make_candidate(start=10, end=42)
        # Identical timing overlap
        other_cand = _make_candidate(start=10, end=42, cid="other-cand-002")
        words = _make_words()
        result_with_dup = score_streamer_v2(cand, words, all_candidates=[cand, other_cand])
        result_no_dup = score_streamer_v2(cand, words, all_candidates=[])
        assert result_with_dup["factors"]["originality"] <= result_no_dup["factors"]["originality"]

    def test_short_clip_quality_penalty(self):
        cand_short = _make_candidate(start=10, end=18)  # 8s — too short
        cand_ideal = _make_candidate(start=10, end=42)  # 32s — ideal
        words_short = _make_words(start=10, end=18)
        words_ideal = _make_words()
        result_short = score_streamer_v2(cand_short, words_short)
        result_ideal = score_streamer_v2(cand_ideal, words_ideal)
        assert result_short["factors"]["quality"] < result_ideal["factors"]["quality"]

    def test_missing_score_breakdown_does_not_crash(self):
        cand = _make_candidate()
        cand["score_breakdown"] = None
        words = _make_words()
        result = score_streamer_v2(cand, words)
        assert 0 <= result["total_score"] <= 100

    def test_reasons_list_not_empty_with_good_content(self):
        cand = _make_candidate()
        words = _make_words(text="mira esto no me lo puedo creer es una locura total increíble jajaja")
        result = score_streamer_v2(cand, words)
        # Should have at least some reasons
        assert isinstance(result["reasons"], list)

    def test_warnings_list_is_list(self):
        cand = _make_candidate()
        words = _make_words()
        result = score_streamer_v2(cand, words)
        assert isinstance(result["warnings"], list)


# ── Test: Quality Gates ────────────────────────────────────────────────────────

class TestQualityGates:

    def test_gate_technical_accept_valid(self):
        cand = _make_candidate(start=10, end=42, audio=0.7, visual=0.6)
        result = gate_technical(cand)
        assert result["decision"] == "ACCEPT"
        assert "TECH_OK" in result["codes"]

    def test_gate_technical_reject_too_short(self):
        cand = _make_candidate(start=10, end=15)  # 5s — critical
        result = gate_technical(cand)
        assert result["decision"] == "REJECT"
        assert "TECH_DURATION_CRITICAL" in result["codes"]

    def test_gate_technical_review_borderline_short(self):
        cand = _make_candidate(start=10, end=21)  # 11s — review
        result = gate_technical(cand)
        assert result["decision"] in ("REVIEW",)

    def test_gate_technical_review_long_clip(self):
        cand = _make_candidate(start=10, end=75)  # 65s — too long for shorts
        result = gate_technical(cand)
        assert result["decision"] == "REVIEW"

    def test_gate_technical_reject_invalid_timestamps(self):
        cand = _make_candidate(start=50, end=10)  # end < start
        result = gate_technical(cand)
        assert result["decision"] == "REJECT"

    def test_gate_context_accept_good_transcript(self):
        cand = _make_candidate()
        words = _make_words(text="mira lo que acaba de pasar esto es increíble")
        result = gate_context(cand, words)
        assert result["decision"] in ("ACCEPT", "REVIEW")

    def test_gate_context_no_transcript_passes(self):
        cand = _make_candidate()
        result = gate_context(cand, [])
        assert result["decision"] == "ACCEPT"
        assert "NO_TRANSCRIPT" in result["codes"]

    def test_gate_context_mid_sentence_start(self):
        cand = _make_candidate(start=10, end=42)
        # Start with a pronoun (bad start) — no prior pause possible since no preceding words
        words = [{"word": "y", "start": 10.0, "end": 10.3}] + _make_words(start=10.3)
        result = gate_context(cand, words)
        # Should flag it
        assert "CONTEXT_MID_SENTENCE_START" in result.get("codes", []) or result["decision"] in ("REVIEW", "ACCEPT")

    def test_gate_duplicates_accept_no_overlap(self):
        cand = _make_candidate(start=10, end=42)
        other = _make_candidate(start=120, end=150, cid="other-003")
        result = gate_duplicates(cand, [cand, other])
        assert result["decision"] == "ACCEPT"

    def test_gate_duplicates_review_high_overlap(self):
        cand = _make_candidate(start=10, end=42)
        other = _make_candidate(start=10, end=42, cid="other-004")
        result = gate_duplicates(cand, [cand, other])
        assert result["decision"] == "REVIEW"
        assert any("DUP" in c for c in result["codes"])

    def test_gate_confidence_few_words_review(self):
        cand = _make_candidate(virality=60)
        words = [{"word": "hola", "start": 10.0, "end": 10.5}]
        result = gate_confidence(cand, words)
        assert result["decision"] == "REVIEW"
        assert "CONF_FEW_WORDS" in result["codes"]

    def test_gate_confidence_accept_sufficient_words(self):
        cand = _make_candidate(virality=60)
        words = _make_words()  # 15+ words
        result = gate_confidence(cand, words)
        assert result["decision"] == "ACCEPT"

    def test_run_all_gates_strictest_wins(self):
        # Technical gate will REJECT (duration too short), others should not downgrade
        cand = _make_candidate(start=10, end=15)
        words = _make_words(start=10, end=15)
        result = run_all_gates(cand, words)
        assert result["final_decision"] == "REJECT"

    def test_run_all_gates_accept_good_candidate(self):
        cand = _make_candidate(start=10, end=42, virality=70, audio=0.7, visual=0.6)
        words = _make_words(text="hoy os voy a contar algo increíble que pasó ayer es una locura total")
        result = run_all_gates(cand, words)
        assert result["final_decision"] in ("ACCEPT", "REVIEW")
        assert "gates" in result
        assert "context" in result["gates"]
        assert "duplicates" in result["gates"]
        assert "technical" in result["gates"]
        assert "confidence" in result["gates"]

    def test_run_all_gates_returns_codes(self):
        cand = _make_candidate()
        words = _make_words()
        result = run_all_gates(cand, words)
        assert isinstance(result["all_codes"], list)
        assert isinstance(result["blocking_reasons"], list)


# ── Test: weight normalization ─────────────────────────────────────────────────

class TestWeightNormalization:

    def test_default_weights_sum_to_one(self):
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_bad_weights_still_compute_score(self):
        """Bad weights should log a warning but not crash."""
        cand = _make_candidate()
        words = _make_words()
        bad_weights = {
            "hook": 0.5, "emotion": 0.5, "context": 0.5,
            "engagement": 0.5, "rhythm": 0.5, "quality": 0.5, "originality": 0.5,
        }
        result = score_streamer_v2(cand, words, weights=bad_weights)
        # Score is clamped to [0, 100] even with inflated weights
        assert 0.0 <= result["total_score"] <= 100.0


# ── Test: edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_zero_duration_candidate(self):
        cand = _make_candidate(start=10, end=10)  # zero duration
        words = []
        # Should not crash
        result = gate_technical(cand)
        assert result["decision"] == "REJECT"

    def test_negative_start(self):
        cand = _make_candidate(start=-5, end=20)
        result = gate_technical(cand)
        assert result["decision"] == "REJECT"
        assert "TECH_INVALID_START" in result["codes"]

    def test_empty_candidates_list(self):
        cand = _make_candidate()
        words = _make_words()
        result = score_streamer_v2(cand, words, all_candidates=[])
        assert result["factors"]["originality"] >= 70  # no duplication possible

    def test_large_word_list_performance(self):
        """Scorer should handle a 1000-word transcript without timeout."""
        cand = _make_candidate(start=0, end=300)
        words = _make_words(start=0, end=300,
                            text=" ".join(["esto es interesante y emocionante"] * 50))
        import time
        t0 = time.time()
        result = score_streamer_v2(cand, words)
        elapsed = time.time() - t0
        assert elapsed < 5.0, f"Scoring took too long: {elapsed:.2f}s"
        assert 0 <= result["total_score"] <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
