"""Heuristic semantic analysis of transcript segments — no LLM required.

Expanded v2: ~3x larger word banks, internet-speak patterns, narrative arc detection,
question-type detection, cliffhanger signals, relatability markers, educational hooks,
and a more nuanced multi-signal scoring formula.
"""
import re
import math
from typing import Optional


# ── Hook phrases ───────────────────────────────────────────────────────────────
# Expanded from 38 → 90+ patterns covering classic, podcast, TikTok/YouTube styles

HOOK_PHRASES = [
    # Classic attention-grabbers
    "you won't believe", "i can't believe", "nobody knows", "nobody talks about",
    "the secret", "here's the thing", "here's what", "here's how", "here's why",
    "most people don't", "most people think", "most people never",
    "stop doing", "stop saying", "stop telling",
    "the reason why", "the real reason", "the truth about", "the truth is",
    "what if i told you", "what nobody tells you",
    "i never told anyone", "i've never told anyone", "i've never said this",
    "wait", "wait wait wait", "hold on", "hold on hold on",
    "turns out", "it turns out",
    "you need to know", "you need to hear",
    "this is why", "that's why", "and that's when",
    "did you know", "did you hear",
    "the problem is", "the biggest problem",
    "the biggest mistake", "my biggest mistake",
    "i learned", "i realized", "i discovered", "i found out",
    "actually works", "it actually", "this actually",
    "no way", "there's no way", "i had no idea",
    "i was wrong", "i was completely wrong",
    "everything changed", "changed everything",
    "the moment i", "that's the moment",
    "listen to this", "listen",
    "imagine", "imagine if",
    "what happened was", "here's what happened",
    "and then", "but then", "so then",
    "plot twist", "spoiler",
    "confession", "i have to confess",
    "honest", "honestly", "to be honest", "to be completely honest",
    "unpopular opinion", "controversial",
    "life changing", "game changer", "game changing",
    # Educational / informational hooks
    "what most people get wrong", "the one thing", "one simple",
    "i'm going to show you", "let me show you", "let me explain",
    "here's the catch", "here's the problem", "here's the secret",
    "the key is", "the answer is", "the solution is",
    "step by step", "the formula", "the method",
    "this changed my life", "changed my mind", "changed how i",
    "research shows", "studies show", "science says", "experts say",
    "the data shows", "the statistics", "the numbers",
    # Personal story hooks
    "true story", "real story", "this actually happened",
    "so i was", "so i did", "so i tried", "so i went",
    "last year i", "last month i", "last week i",
    "when i was", "back when i", "back in",
    "at one point", "at that point", "that was the moment",
    "everything i knew", "nothing was the same",
    # Question-based hooks
    "have you ever", "have you noticed", "have you seen",
    "why does", "why do we", "why is it that",
    "what would you do", "what if you", "what happens when",
    "how many of you", "how often do you",
    # Engagement / curiosity gap hooks
    "keep watching", "stay with me", "don't go anywhere",
    "i'll get to that", "by the end of this",
    "the reason will shock you", "and the reason why is",
    "i'll explain", "let me tell you", "you're going to want to hear this",
    # Controversy / opinion hooks
    "hot take", "controversial opinion", "people hate me for saying this",
    "i got cancelled", "i got called out", "i was exposed",
    "i'm not sorry", "i said what i said", "fight me on this",
    "nobody wants to talk about", "we need to talk about",
    "can we talk about", "can we please talk about",
]

# ── Emotion word banks — expanded ─────────────────────────────────────────────

EMOTION_WORDS = {
    "excitement": [
        "amazing", "incredible", "insane", "unbelievable", "mind-blowing",
        "awesome", "fantastic", "epic", "legendary", "wild", "crazy",
        "holy", "oh my", "oh my god", "omg", "wow", "woah", "whoa",
        "obsessed", "addicted", "cant stop", "can't stop", "hooked",
        "fire", "lit", "bussin", "banger", "slaps", "it slaps",
        "goes hard", "absolute", "insanely", "ridiculously good",
        "best thing", "best ever", "greatest", "goat",
    ],
    "surprise": [
        "shocked", "shocked me", "surprised", "surprising", "unexpected",
        "never expected", "didn't expect", "out of nowhere", "suddenly",
        "all of a sudden", "completely caught", "caught me off guard",
        "blew my mind", "mind blown", "couldn't believe", "wait what",
        "no way", "absolutely not", "what just happened", "plot twist",
        "out of left field", "blindsided", "caught off guard",
        "out of the blue", "randomly", "completely random",
    ],
    "tension": [
        "terrifying", "terrified", "scared", "frightened", "nervous",
        "anxious", "stressed", "panic", "panicking", "danger", "dangerous",
        "risky", "risk", "threatened", "threatening", "worried", "worry",
        "dread", "dreaded", "dreading", "nightmare", "worst case",
        "ticking clock", "running out of time", "last chance",
        "heart racing", "hands shaking", "stomach dropped",
        "couldn't breathe", "throat tight", "adrenaline",
    ],
    "humor": [
        "hilarious", "funny", "laughing", "lol", "lmao", "haha", "hahaha",
        "joke", "joking", "kidding", "just kidding", "absurd", "ridiculous",
        "clown", "cringe", "this is so dumb", "i'm crying", "dead",
        "i'm dead", "i'm deceased", "no literally", "i cannot",
        "the audacity", "the nerve", "unhinged", "chaotic", "feral",
        "not me", "it's giving", "the way i", "living for this",
        "rent free", "in my head rent free", "lowkey",
    ],
    "anger": [
        "angry", "furious", "outraged", "disgusted", "disrespected",
        "disrespect", "unacceptable", "fed up", "had enough", "enough is enough",
        "not okay", "absolutely not", "no way", "appalling", "infuriating",
        "makes me sick", "makes me mad", "drives me crazy", "drives me insane",
        "can't stand", "can't deal", "done with", "over it",
        "calling this out", "holding them accountable", "not letting this slide",
        "this needs to stop", "enough", "enough already",
    ],
    "sadness": [
        "sad", "crying", "cried", "tears", "heartbroken", "devastated",
        "disappointed", "terrible", "awful", "horrible", "gutted",
        "crushed", "destroyed", "lost everything", "fell apart",
        "broke down", "couldn't handle", "the hardest", "darkest",
        "rock bottom", "lowest point", "hit rock bottom",
        "couldn't get out of bed", "stopped caring", "gave up",
    ],
    "revelation": [
        "realized", "figured out", "found out", "discovered", "learned",
        "now i know", "turns out", "it turns out", "truth", "true story",
        "real story", "what really", "the real", "the truth",
        "the answer", "the reason", "the secret", "finally understood",
        "connecting the dots", "it all makes sense", "suddenly clear",
        "clicked", "it clicked", "everything clicked", "now i get it",
        "i finally get it", "the missing piece", "all along",
    ],
    "inspiration": [
        "inspiring", "motivated", "motivated me", "push through",
        "never give up", "keep going", "worth it", "so worth it",
        "changed everything", "turned my life around", "best decision",
        "grateful", "thankful", "blessed", "overcome", "overcame",
        "didn't stop", "pushed through", "made it", "we made it",
        "finally", "finally did it", "proof that", "possible",
        "you can do this", "you can do it", "believe me",
    ],
    "relatability": [
        "we've all been there", "you know the feeling", "you know what i mean",
        "happens to everyone", "guilty", "guilty of this", "same",
        "literally me", "this is me", "oh god that's me",
        "i do this too", "anyone else", "am i the only one",
        "tell me i'm not the only one", "normalize this",
        "real talk", "no cap", "i'm not even lying", "deadass",
        "facts", "big facts", "on god", "for real",
    ],
}

# ── Conflict / drama words ─────────────────────────────────────────────────────

CONFLICT_WORDS = [
    "fight", "fighting", "argument", "arguing", "argued", "disagree", "disagreed",
    "disagreement", "confronted", "confrontation", "called out", "called me out",
    "accused", "accuse", "lied", "lying", "cheat", "cheated", "cheating",
    "betrayed", "betrayal", "backstab", "two-faced", "fake", "fraud",
    "against", "versus", "debate", "controversy", "controversial", "drama",
    "cancel", "cancelled", "exposed", "expose",
    "toxic", "abuse", "abusive", "manipulative", "gaslit", "gaslighting",
    "red flag", "red flags", "walking on eggshells", "nothing i did",
    "cut them off", "blocked them", "left", "walked out", "walked away",
    "stood up for myself", "finally said", "confronted them",
    "went off", "snapped", "lost it", "couldn't take it anymore",
]

# ── Story structure signals ────────────────────────────────────────────────────

STORY_SETUP_WORDS = [
    "so", "so basically", "ok so", "okay so", "alright so",
    "yesterday", "last week", "last month", "last year", "the other day",
    "a while ago", "back in", "back when", "when i was",
    "i was", "i went", "i got", "i had",
    "here's what happened", "so what happened",
    "let me tell you", "let me explain",
    "for context", "for those who don't know",
    "basically", "essentially", "long story short",
    "it started when", "it all started", "this all started",
    "there was this", "there was a",
    "so i met", "so i found", "so i saw", "so i heard",
]

ESCALATION_WORDS = [
    "then", "and then", "but then", "so then", "after that",
    "suddenly", "out of nowhere", "all of a sudden",
    "things got", "it got", "it got worse", "it escalated",
    "next thing", "the next thing i know",
    "that's when", "that's when things",
    "started to", "began to",
    "more and more", "worse and worse",
    "kept", "kept getting", "kept happening",
    "couldn't stop", "wouldn't stop",
    "things got serious", "things got real",
    "hours later", "days later", "minutes later",
]

PAYOFF_WORDS = [
    "and that's", "so that's", "turns out", "ended up",
    "final", "finally", "in the end", "at the end",
    "the result", "the outcome",
    "i survived", "we made it", "we did it",
    "it worked", "it didn't work",
    "punchline", "the punchline is",
    "moral", "moral of the story", "lesson learned",
    "never again", "first and last time",
    "worth it", "not worth it",
    "full circle", "came full circle",
    "now i know", "now i understand", "looking back",
    "i'll never forget", "changed everything",
    "that was it", "that was the moment", "that's what did it",
]

# ── Cliffhanger / anticipation signals ────────────────────────────────────────

CLIFFHANGER_WORDS = [
    "you'll never guess", "guess what happened", "guess what they said",
    "and you won't believe what", "here's where it gets crazy",
    "here's where it gets good", "it gets worse", "it gets better",
    "wait for it", "but wait", "but here's the thing",
    "and that's not even", "that's not the worst part", "that's not the best part",
    "i'm not done", "there's more", "but there's a catch",
    "oh but it gets better", "oh but it gets worse",
    "brace yourself", "you're not ready for this",
]

# ── Question patterns ──────────────────────────────────────────────────────────

RHETORICAL_QUESTIONS = [
    "why would anyone", "why do people", "how is that possible",
    "what kind of person", "how could someone",
    "is it just me", "am i crazy", "am i wrong",
    "does anyone else", "can anyone explain",
    "why aren't we talking about", "why is nobody talking about",
]

# ── Personal narrative markers ─────────────────────────────────────────────────

PERSONAL_STORY_MARKERS = [
    "i grew up", "growing up i", "as a kid", "when i was a kid",
    "my parents", "my mom", "my dad", "my family",
    "at my job", "at work", "my boss", "my coworker", "my colleague",
    "my friend", "my best friend", "my ex", "my partner", "my girlfriend", "my boyfriend",
    "my husband", "my wife", "my relationship",
    "in school", "in college", "in high school", "my teacher",
    "first time i", "the day i", "the night i", "the moment i",
    "i'll never forget", "i still remember", "to this day",
]

# ── Educational / value-add markers ───────────────────────────────────────────

EDUCATIONAL_MARKERS = [
    "here's what you need to know", "here's how it works",
    "the way it works is", "the reason this happens",
    "most people don't realize", "most people don't know",
    "what they don't tell you", "what nobody tells you",
    "the correct way", "the right way", "the wrong way",
    "common misconception", "myth", "debunking", "actually false",
    "technically", "technically speaking", "here's the science",
    "the research", "according to", "studies found",
    "tip", "pro tip", "life hack", "hack", "trick",
    "this works because", "here's why this works",
]

# ── Standalone detection ───────────────────────────────────────────────────────

STANDALONE_PENALTY_STARTERS = [
    "he", "she", "it", "they", "we", "that", "this", "those", "these",
    "him", "her", "them", "his", "hers", "their",
    "which", "who", "what", "where", "when", "how",
    "but", "and", "or", "so", "then", "because", "since", "although",
]

STANDALONE_INTRO_PHRASES = [
    "my name", "i'm", "we're", "this is", "today we", "today i",
    "welcome to", "in this video", "in today's video",
    "so today", "so basically", "ok so", "okay so",
    "long story short", "let me explain", "let me tell you",
    "real quick", "quick story", "storytime",
    "true story", "this really happened",
]


# ── Core analysis function ─────────────────────────────────────────────────────

def analyze_segment(words: list[dict], start_s: float, end_s: float) -> dict:
    """Return full semantic analysis for a word-level transcript segment."""
    if not words:
        return _empty_result(start_s)

    w_in = [w for w in words if w["start"] >= start_s - 0.1 and w["end"] <= end_s + 0.1]
    if not w_in:
        return _empty_result(start_s)

    text = " ".join(w["word"] for w in w_in).lower()
    text_raw = " ".join(w["word"] for w in w_in)
    duration = max(end_s - start_s, 1.0)

    # ── Emotion scoring — 8 categories, weighted by impact ────────────────────
    emotion_hits = {}
    for emo, elist in EMOTION_WORDS.items():
        hits = sum(1 for e in elist if e in text)
        if hits:
            emotion_hits[emo] = hits
    high_impact_emotions = {"excitement", "tension", "anger", "sadness", "surprise"}
    raw_emotion = sum(v for emo, v in emotion_hits.items() if emo in high_impact_emotions)
    support_emotion = sum(v for emo, v in emotion_hits.items() if emo not in high_impact_emotions)
    emotion_score = min(1.0, raw_emotion * 0.13 + support_emotion * 0.07)

    # ── Hook strength ──────────────────────────────────────────────────────────
    first_words = " ".join(w["word"] for w in w_in[:15]).lower()
    hook_hits = sum(1 for p in HOOK_PHRASES if p in text)
    hook_in_opening = sum(1 for p in HOOK_PHRASES if p in first_words)
    cliffhanger_hits = sum(1 for p in CLIFFHANGER_WORDS if p in text)
    rhetorical_hits = sum(1 for p in RHETORICAL_QUESTIONS if p in text)
    hook_strength = min(1.0,
        hook_hits * 0.14 +
        hook_in_opening * 0.22 +
        cliffhanger_hits * 0.10 +
        rhetorical_hits * 0.08
    )
    opening_text = text[:120]
    if "?" in opening_text:
        hook_strength = min(1.0, hook_strength + 0.12)
    if "!" in opening_text:
        hook_strength = min(1.0, hook_strength + 0.08)

    # ── Semantic interest — extended signal mix ────────────────────────────────
    conflict_hits = sum(1 for c in CONFLICT_WORDS if c in text)
    educational_hits = sum(1 for e in EDUCATIONAL_MARKERS if e in text)
    personal_hits = sum(1 for p in PERSONAL_STORY_MARKERS if p in text)
    semantic_interest = min(1.0,
        hook_strength * 0.35 +
        emotion_score * 0.30 +
        min(1.0, conflict_hits * 0.18) * 0.20 +
        min(1.0, educational_hits * 0.25) * 0.10 +
        min(1.0, personal_hits * 0.20) * 0.05
    )

    # Story structure bonus
    has_setup = any(p in text for p in STORY_SETUP_WORDS)
    has_escalation = any(p in text for p in ESCALATION_WORDS)
    has_payoff = any(p in text for p in PAYOFF_WORDS)
    has_cliffhanger = any(p in text for p in CLIFFHANGER_WORDS)
    story_bonus = (
        has_setup * 0.10 +
        has_escalation * 0.07 +
        has_payoff * 0.13 +
        has_cliffhanger * 0.08
    )
    semantic_interest = min(1.0, semantic_interest + story_bonus)

    # ── Sub-scores ─────────────────────────────────────────────────────────────
    revelation_words_found = sum(1 for r in EMOTION_WORDS["revelation"] if r in text)
    revelation_score = min(1.0, revelation_words_found * 0.20)

    humor_words_found = sum(1 for h in EMOTION_WORDS["humor"] if h in text)
    humor_score = min(1.0, humor_words_found * 0.18)

    relatability_hits = sum(1 for r in EMOTION_WORDS["relatability"] if r in text)
    relatability_score = min(1.0, relatability_hits * 0.25)

    conflict_score = min(1.0, conflict_hits * 0.18)

    # ── Standalone value ───────────────────────────────────────────────────────
    first_word = w_in[0]["word"].lower().strip(".,!?")
    standalone_penalty = 0.30 if first_word in STANDALONE_PENALTY_STARTERS else 0.0
    standalone_bonus = 0.0
    if any(p in text for p in STANDALONE_INTRO_PHRASES):
        standalone_bonus += 0.20
    if personal_hits >= 2:
        standalone_bonus += 0.10
    if has_setup and has_payoff:
        standalone_bonus += 0.15
    standalone_value = max(0.1, min(1.0, 0.5 + standalone_bonus - standalone_penalty))

    # ── Shareability ───────────────────────────────────────────────────────────
    shareability = min(1.0,
        hook_strength      * 0.28 +
        emotion_score      * 0.22 +
        revelation_score   * 0.18 +
        humor_score        * 0.14 +
        conflict_score     * 0.08 +
        relatability_score * 0.10
    )

    # ── Content type ───────────────────────────────────────────────────────────
    content_type = _classify_type(
        hook_in_opening, conflict_hits, humor_words_found,
        revelation_words_found, educational_hits, personal_hits,
        relatability_hits, has_cliffhanger
    )

    # ── Hook time ─────────────────────────────────────────────────────────────
    hook_time = _find_hook_time(w_in, start_s)

    # ── Reasons ───────────────────────────────────────────────────────────────
    reasons = _build_reasons(
        hook_hits, hook_in_opening, emotion_hits, conflict_hits,
        revelation_words_found, humor_words_found, relatability_hits,
        has_setup, has_escalation, has_payoff, has_cliffhanger,
        hook_strength, emotion_score, educational_hits, personal_hits
    )

    return {
        "emotion_score":      round(emotion_score, 3),
        "hook_strength":      round(hook_strength, 3),
        "semantic_interest":  round(semantic_interest, 3),
        "standalone_value":   round(standalone_value, 3),
        "conflict_score":     round(conflict_score, 3),
        "humor_score":        round(humor_score, 3),
        "revelation_score":   round(revelation_score, 3),
        "shareability":       round(shareability, 3),
        "relatability_score": round(relatability_score, 3),
        "educational_score":  round(min(1.0, educational_hits * 0.25), 3),
        "content_type":       content_type,
        "story_structure": {
            "has_setup":       has_setup,
            "has_escalation":  has_escalation,
            "has_payoff":      has_payoff,
            "has_cliffhanger": has_cliffhanger,
        },
        "hook_time": round(hook_time, 2),
        "reasons":   reasons,
    }


def _classify_type(hook_in_opening, conflict_hits, humor_hits, revelation_hits,
                   educational_hits, personal_hits, relatability_hits,
                   has_cliffhanger) -> str:
    """Classify the dominant content type of a segment."""
    scores = {
        "hook":        hook_in_opening * 3 + (1 if has_cliffhanger else 0) * 2,
        "conflict":    conflict_hits * 2,
        "humor":       humor_hits * 2,
        "revelation":  revelation_hits * 2,
        "educational": educational_hits * 2,
        "story":       personal_hits,
        "relatable":   relatability_hits,
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def _find_hook_time(words: list[dict], base_start: float) -> float:
    """Seconds from segment start until first high-interest word."""
    high_interest = {"!", "?", "wow", "wait", "omg", "oh", "no", "holy", "what"}
    for w in words:
        wl = w["word"].lower().strip(".,!?\"'")
        if wl in high_interest or "!" in w["word"] or "?" in w["word"]:
            return max(0.0, w["start"] - base_start)
        if any(p.startswith(wl) for p in HOOK_PHRASES[:20]):
            return max(0.0, w["start"] - base_start)
    return max(0.0, (words[-1]["start"] - base_start) * 0.5) if words else 0.0


def _build_reasons(hook_hits, hook_in_opening, emotion_hits, conflict_hits,
                   revelation_hits, humor_hits, relatability_hits,
                   has_setup, has_escalation, has_payoff, has_cliffhanger,
                   hook_strength, emotion_score, educational_hits, personal_hits) -> list[str]:
    reasons = []
    if hook_in_opening >= 1:
        reasons.append("Strong opening hook")
    elif hook_hits >= 2:
        reasons.append("Multiple hook phrases")
    elif hook_hits == 1:
        reasons.append("Hook phrase detected")

    if "excitement" in emotion_hits:
        reasons.append("High excitement energy")
    if "surprise" in emotion_hits:
        reasons.append("Surprise/shock moment")
    if "tension" in emotion_hits:
        reasons.append("Tension and stakes")
    if "humor" in emotion_hits or humor_hits:
        reasons.append("Humor detected")
    if "anger" in emotion_hits:
        reasons.append("Emotional confrontation")
    if "revelation" in emotion_hits or revelation_hits:
        reasons.append("Revelation or discovery")
    if "inspiration" in emotion_hits:
        reasons.append("Inspirational content")
    if "relatability" in emotion_hits or relatability_hits:
        reasons.append("Highly relatable")

    if conflict_hits >= 2:
        reasons.append("High conflict engagement")
    elif conflict_hits == 1:
        reasons.append("Conflict present")

    if educational_hits >= 2:
        reasons.append("Strong educational value")
    elif educational_hits == 1:
        reasons.append("Educational content")

    if personal_hits >= 2:
        reasons.append("Personal narrative")

    if has_cliffhanger:
        reasons.append("Cliffhanger moment")

    if has_setup and has_payoff:
        reasons.append("Complete story arc")
    elif has_setup and has_escalation:
        reasons.append("Setup + escalation")
    elif has_payoff:
        reasons.append("Strong payoff")

    if hook_strength > 0.7:
        reasons.append("Exceptional hook strength")
    if emotion_score > 0.6:
        reasons.append("High emotional intensity")

    return reasons[:7]


def _empty_result(start_s: float) -> dict:
    return {
        "emotion_score": 0.0, "hook_strength": 0.0, "semantic_interest": 0.0,
        "standalone_value": 0.5, "conflict_score": 0.0, "humor_score": 0.0,
        "revelation_score": 0.0, "shareability": 0.0, "relatability_score": 0.0,
        "educational_score": 0.0, "content_type": "other",
        "story_structure": {
            "has_setup": False, "has_escalation": False,
            "has_payoff": False, "has_cliffhanger": False,
        },
        "hook_time": 0.0, "reasons": [],
    }


# ── Smart boundary detection ───────────────────────────────────────────────────

def find_smart_start(words: list[dict], target_time: float, window_s: float = 12.0) -> float:
    """Find a natural start within [target_time - window_s, target_time + window_s/2]."""
    lo = target_time - window_s
    hi = target_time + window_s / 2

    candidates_in = [w for w in words if lo <= w["start"] <= hi]
    if not candidates_in:
        return target_time

    best = target_time
    best_score = -1.0

    for i, w in enumerate(candidates_in):
        score = 0.0
        wl = w["word"].lower().strip(".,!?\"'")

        if wl not in STANDALONE_PENALTY_STARTERS:
            score += 0.4

        if i > 0:
            prev_end = candidates_in[i - 1]["end"]
            pause = w["start"] - prev_end
            if pause >= 0.5:
                score += 0.5
            elif pause >= 0.25:
                score += 0.25

        if i == 0 or (i > 0 and any(candidates_in[i-1]["word"].endswith(p) for p in [".", "!", "?"])):
            score += 0.3

        if any(wl in p for p in HOOK_PHRASES[:20]):
            score += 0.4

        if wl in {"what", "why", "how", "when", "where", "who", "did", "have", "can"}:
            score += 0.2

        distance_penalty = abs(w["start"] - target_time) / window_s * 0.3
        score -= distance_penalty

        if score > best_score:
            best_score = score
            best = w["start"]

    return round(best, 3)


def find_smart_end(words: list[dict], target_time: float, window_s: float = 12.0) -> float:
    """Find a natural end within [target_time - window_s/2, target_time + window_s]."""
    lo = target_time - window_s / 2
    hi = target_time + window_s

    candidates_in = [w for w in words if lo <= w["end"] <= hi]
    if not candidates_in:
        return target_time

    best = target_time
    best_score = -1.0

    for i, w in enumerate(candidates_in):
        score = 0.0
        word_text = w["word"]

        if word_text.endswith((".", "!", "?")):
            score += 0.6
        elif word_text.endswith((",", ";", ":")):
            score += 0.2

        if i + 1 < len(candidates_in):
            next_start = candidates_in[i + 1]["start"]
            pause = next_start - w["end"]
            if pause >= 0.5:
                score += 0.5
            elif pause >= 0.25:
                score += 0.25

        payoff_closers = [
            "finally", "exactly", "right", "seriously", "unbelievable",
            "insane", "crazy", "incredible", "period", "forever",
            "everything", "nothing", "always", "never", "anymore",
        ]
        if any(p in word_text.lower() for p in payoff_closers):
            score += 0.3

        distance_penalty = abs(w["end"] - target_time) / window_s * 0.3
        score -= distance_penalty

        if score > best_score:
            best_score = score
            best = w["end"]

    return round(best, 3)


# ── Retention score ────────────────────────────────────────────────────────────

def compute_retention_score(words: list[dict], start_s: float, end_s: float) -> dict:
    """Compute retention-related metrics for a segment."""
    w_in = [w for w in words if w["start"] >= start_s - 0.1 and w["end"] <= end_s + 0.1]
    duration = max(end_s - start_s, 1.0)

    if not w_in:
        return {"retention_score": 0.4, "hook_time": duration / 2, "pacing": 0.0,
                "dead_air_ratio": 1.0, "progression": 0.3}

    # Pacing: words per second (ideal ~2.0–3.5)
    wps = len(w_in) / duration
    if 2.0 <= wps <= 3.5:
        pacing_score = 1.0
    elif wps < 2.0:
        pacing_score = max(0.2, wps / 2.0)
    else:
        pacing_score = max(0.5, 1.0 - (wps - 3.5) / 5.0)

    # Dead air
    spoken_duration = sum(max(0, w["end"] - w["start"]) for w in w_in)
    dead_air_ratio = max(0.0, 1.0 - spoken_duration / duration)
    dead_air_score = max(0.0, 1.0 - dead_air_ratio * 1.5)

    # Hook time
    sem = analyze_segment(w_in, start_s, end_s)
    hook_time = sem["hook_time"]
    hook_time_score = max(0.0, 1.0 - hook_time / 10.0)

    # Content density
    content_density = min(1.0, (
        sem["hook_strength"]    * 0.3 +
        sem["emotion_score"]    * 0.3 +
        sem["semantic_interest"] * 0.4
    ))

    # Progression: first vs second half, reward escalation
    mid = start_s + duration / 2
    first_half = [w for w in w_in if w["start"] < mid]
    second_half = [w for w in w_in if w["start"] >= mid]
    s1 = analyze_segment(first_half, start_s, mid) if first_half else _empty_result(start_s)
    s2 = analyze_segment(second_half, mid, end_s) if second_half else _empty_result(mid)
    avg_interest = (s1["semantic_interest"] + s2["semantic_interest"]) / 2
    escalation_bonus = max(0.0, (s2["semantic_interest"] - s1["semantic_interest"]) * 0.1)
    progression_score = min(1.0, avg_interest + 0.15 + escalation_bonus)

    retention_score = (
        hook_time_score   * 0.25 +
        pacing_score      * 0.20 +
        dead_air_score    * 0.15 +
        progression_score * 0.20 +
        content_density   * 0.20
    )

    return {
        "retention_score": round(min(1.0, retention_score), 3),
        "hook_time":       round(hook_time, 2),
        "pacing":          round(pacing_score, 3),
        "dead_air_ratio":  round(dead_air_ratio, 3),
        "progression":     round(progression_score, 3),
    }
