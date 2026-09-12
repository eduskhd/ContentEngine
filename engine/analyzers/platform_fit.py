"""Platform fit analysis: score each clip against platform requirements."""
from engine.config import CONFIG
from engine import database as db

PLATFORM_SPECS = {
    "tiktok": {
        "aspect_ratio": (9, 16),
        "min_duration": 15,
        "max_duration": 60,
        "ideal_duration": (20, 45),
        "captions_required": True,
        "hook_importance": 0.9,
    },
    "instagram": {
        "aspect_ratio": (9, 16),
        "min_duration": 3,
        "max_duration": 60,
        "ideal_duration": (15, 45),
        "captions_required": True,
        "hook_importance": 0.8,
    },
    "youtube": {
        "aspect_ratio": (9, 16),
        "min_duration": 15,
        "max_duration": 60,
        "ideal_duration": (30, 60),
        "captions_required": False,
        "hook_importance": 0.7,
    },
}


def score_platform_fit(candidate: dict, platforms: list[str]) -> dict[str, float]:
    duration = candidate["end_s"] - candidate["start_s"]
    hook = candidate.get("hook_score", 50.0) / 100.0
    scores = {}

    for platform in platforms:
        spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["tiktok"])
        score = 1.0

        if not (spec["min_duration"] <= duration <= spec["max_duration"]):
            score *= 0.5
        elif spec["ideal_duration"][0] <= duration <= spec["ideal_duration"][1]:
            score *= 1.0
        else:
            score *= 0.8

        score = score * (1 - spec["hook_importance"]) + hook * spec["hook_importance"]
        scores[platform] = round(min(1.0, score) * 100, 2)

    return scores


def analyze_platform_fit(job_id: str, candidates: list[dict], platforms: list[str]) -> None:
    for cand in candidates:
        scores = score_platform_fit(cand, platforms)
        db.update_candidate(cand["id"], platform_scores=scores)
