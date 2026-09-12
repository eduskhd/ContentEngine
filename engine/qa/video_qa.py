"""Video QA: technical + visual quality checks. FAIL CLOSED on uncertainty."""
import subprocess
import json
import os
from pathlib import Path

from engine.config import CONFIG
from engine import database as db

TECHNICAL_CHECKS = {
    "resolution_ok": lambda m: m["width"] >= 1080 and m["height"] >= 1920,
    "duration_ok": lambda m: 10 <= m["duration"] <= 65,
    "fps_ok": lambda m: m["fps"] >= 24,
    "file_ok": lambda m: m["size"] > 10_000,
    "has_audio": lambda m: m.get("has_audio", False),
}


def run_qa(job_id: str, clip_ids: list[str]) -> dict[str, str]:
    """Returns {clip_id: 'PASS'|'FAIL'|'WARN'}."""
    results = {}
    with db.db() as conn:
        for clip_id in clip_ids:
            row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
            path = row["captioned_path"] or row["output_path"]
            if not path or not os.path.exists(path):
                db_update_qa(conn, clip_id, "FAIL", "FAIL", ["file_missing"])
                results[clip_id] = "FAIL"
                continue

            meta = _probe(path)
            tech_result, tech_issues = _technical_qa(meta)
            visual_result, visual_issues = _visual_qa(path, meta)

            db_update_qa(conn, clip_id, tech_result, visual_result, tech_issues + visual_issues)
            results[clip_id] = "PASS" if tech_result == "PASS" and visual_result == "PASS" else \
                                "WARN" if "FAIL" not in [tech_result, visual_result] else "FAIL"
    return results


def db_update_qa(conn, clip_id, tech, visual, issues):
    conn.execute(
        "UPDATE clips SET technical_qa=?, visual_qa=?, qa_notes=? WHERE id=?",
        (tech, visual, json.dumps({"issues": issues}), clip_id)
    )


def _technical_qa(meta: dict) -> tuple[str, list]:
    issues = [name for name, check in TECHNICAL_CHECKS.items() if not _safe_check(check, meta)]
    if not issues:
        return "PASS", []
    critical = [i for i in issues if "resolution" in i or "file" in i]
    return ("FAIL" if critical else "WARN"), issues


def _safe_check(check, meta):
    try:
        return check(meta)
    except Exception:
        return False


def _visual_qa(path: str, meta: dict) -> tuple[str, list]:
    issues = []
    if meta["duration"] < 10:
        issues.append("too_short")
    if meta["size"] < 50_000:
        issues.append("file_too_small")
    return ("FAIL" if issues else "PASS"), issues


def _probe(path: str) -> dict:
    cmd = [
        CONFIG.ffprobe_path, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode != 0:
        return {}
    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    vs = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    as_ = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps_str = vs.get("r_frame_rate", "30/1")
    if "/" in str(fps_str):
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    else:
        fps = float(fps_str)
    return {
        "duration": float(fmt.get("duration", 0)),
        "size": int(fmt.get("size", 0)),
        "width": vs.get("width", 0),
        "height": vs.get("height", 0),
        "fps": round(fps, 3),
        "has_audio": as_ is not None,
    }
