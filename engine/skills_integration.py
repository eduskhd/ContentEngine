"""Skills integration: run Claude Code skills as specialized advisors."""
import subprocess
import json
import time
import os
from pathlib import Path

from engine.config import CONFIG
from engine import database as db


SKILL_PROMPTS = {
    "virality-analyzer": """Analyze this video clip segment for virality potential.
Segment: {start}s to {end}s
Transcript: {transcript}
Visual score: {visual_score}
Audio score: {audio_score}

Rate virality 0-100 and explain in 2-3 sentences. Focus on: hook strength, shareability, retention.
Return JSON: {{"score": 75, "reasoning": "...", "hook_verdict": "strong|weak|moderate"}}""",

    "hook-anatomy": """Analyze the hook quality of this content opener.
First 3 seconds transcript: {hook_text}
Full segment transcript: {transcript}

Rate hook 0-100 and identify the hook type.
Return JSON: {{"score": 70, "hook_type": "question|statement|contrast|story|shock", "verdict": "..."}}""",

    "platform-fluency": """Assess platform fit for this clip.
Duration: {duration}s
Transcript excerpt: {transcript}
Target platforms: {platforms}

Score each platform 0-100 for fit.
Return JSON: {{"tiktok": 80, "instagram": 75, "youtube": 60, "reasoning": "..."}}""",

    "content-autopsy": """Analyze why this content will succeed or fail.
Virality score: {virality_score}
Hook score: {hook_score}
Transcript: {transcript}

Identify top 2 strengths and top 2 weaknesses.
Return JSON: {{"strengths": [...], "weaknesses": [...], "prediction": "hit|miss|average"}}""",
}


def run_skill(job_id: str, skill_name: str, context: dict) -> dict:
    """Run a skill via Claude API if available, else return scored stub."""
    start_time = time.time()
    skills_dir = Path(CONFIG.skills_dir)
    skill_path = skills_dir / skill_name / "SKILL.md"

    if not skill_path.exists():
        return _stub_response(skill_name, context)

    prompt_template = SKILL_PROMPTS.get(skill_name, "")
    if not prompt_template:
        return _stub_response(skill_name, context)

    prompt = prompt_template.format(**{k: str(v)[:500] for k, v in context.items()})

    result = _call_claude(prompt, skill_path)
    duration_ms = int((time.time() - start_time) * 1000)

    db.log_skill_run(
        job_id, skill_name,
        f"start={context.get('start')} end={context.get('end')}",
        result, result.get("score", 0), duration_ms,
        "OK" if result else "ERROR"
    )
    return result


def _call_claude(prompt: str, skill_path: Path) -> dict:
    """Call Claude via CLI with skill context. Falls back to stub on failure."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
    except Exception:
        pass
    return {}


def _stub_response(skill_name: str, context: dict) -> dict:
    """Heuristic stub when skill or Claude CLI is unavailable."""
    virality = context.get("virality_score", 50.0)
    hook = context.get("hook_score", 50.0)
    transcript = str(context.get("transcript", "")).lower()

    # Simple heuristics as stub
    score = (float(virality) + float(hook)) / 2

    if skill_name == "virality-analyzer":
        return {"score": round(score, 1), "reasoning": "Heuristic estimate", "hook_verdict": "moderate"}
    elif skill_name == "hook-anatomy":
        hook_type = "statement"
        if "?" in transcript[:100]:
            hook_type = "question"
        elif any(w in transcript[:100] for w in ["secret", "never", "always", "wrong"]):
            hook_type = "contrast"
        return {"score": round(float(hook), 1), "hook_type": hook_type, "verdict": "moderate"}
    elif skill_name == "platform-fluency":
        platforms = context.get("platforms", ["tiktok"])
        return {p: round(score * 0.8 + 10, 1) for p in str(platforms).split(",") if p.strip()}
    elif skill_name == "content-autopsy":
        prediction = "hit" if score > 70 else "average" if score > 50 else "miss"
        return {
            "strengths": ["Good pace", "Clear audio"],
            "weaknesses": ["Hook could be stronger", "Context dependency"],
            "prediction": prediction
        }
    return {"score": round(score, 1)}


def run_all_skills(job_id: str, candidates: list[dict], platforms: list[str],
                    words: list[dict]) -> None:
    """Run available skills across all finalist candidates."""
    transcript_map = _build_transcript(words)

    for cand in candidates:
        start_s = cand["start_s"]
        end_s = cand["end_s"]
        transcript = _get_window_transcript(transcript_map, start_s, end_s)
        hook_text = _get_window_transcript(transcript_map, start_s, min(start_s + 3, end_s))

        ctx = {
            "start": start_s, "end": end_s,
            "transcript": transcript[:400],
            "hook_text": hook_text[:200],
            "visual_score": cand.get("visual_score", 0.5) * 100,
            "audio_score": cand.get("audio_score", 0.5) * 100,
            "virality_score": cand.get("virality_score", 50),
            "hook_score": cand.get("hook_score", 50),
            "duration": round(end_s - start_s, 1),
            "platforms": ",".join(platforms),
        }

        for skill_name in ["virality-analyzer", "hook-anatomy", "platform-fluency"]:
            result = run_skill(job_id, skill_name, ctx)
            if result.get("score"):
                if skill_name == "virality-analyzer":
                    db.update_candidate(cand["id"],
                        virality_score=float(result.get("score", cand.get("virality_score", 50))))
                elif skill_name == "hook-anatomy":
                    db.update_candidate(cand["id"],
                        hook_score=float(result.get("score", cand.get("hook_score", 50))))


def _build_transcript(words: list[dict]) -> list[tuple]:
    return [(w["start"], w["end"], w["word"]) for w in words]


def _get_window_transcript(transcript: list[tuple], start: float, end: float) -> str:
    return " ".join(w for s, e, w in transcript if s >= start and e <= end + 0.5)
