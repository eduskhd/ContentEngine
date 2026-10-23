#!/usr/bin/env python3
"""Weekend Autopilot Supervisor — ContentEngine autonomous worker.

Runs Claude Code sessions back-to-back. Recovers from rate limits,
context resets, and terminal restarts via persistent checkpoints.

Usage:
    python supervisor.py              # normal run
    python supervisor.py --test       # verify one cycle then exit
    python supervisor.py --status     # print current state and exit
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
_TOOLS  = Path(__file__).parent
_ROOT   = _TOOLS.parent.parent          # ContentEngine/
_AUDIT  = _ROOT / "audits" / "weekend_stability"
_LOCK   = _TOOLS / ".supervisor.pid"
_STOP   = _TOOLS / ".STOP"
_STATE  = _AUDIT / "MISSION_STATE.json"
_LOG    = _AUDIT / "EXECUTION_LOG.md"

# ── Deadline: Sunday 25-Oct-2026 23:59 Madrid (UTC+2 = UTC 21:59) ──────────────
_DEADLINE = datetime(2026, 10, 25, 21, 59, tzinfo=timezone.utc)

# ── Rate-limit detection ────────────────────────────────────────────────────────
_RATE_PATTERNS = [
    "rate limit", "too many requests", "overloaded",
    "usage limit", "quota exceeded", "please try again",
    "claude is currently unavailable",
]
_RATE_WAIT_INIT = 300       # 5 min initial backoff
_RATE_WAIT_MAX  = 3_600     # 1 hr max
_RATE_WAIT_MULT = 2


# ── Utilities ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _log(msg: str) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    try:
        with _LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _load_state() -> dict:
    if _STATE.exists():
        try:
            return json.loads(_STATE.read_text(encoding="utf-8"))
        except Exception as e:
            _log(f"WARN: Could not load state ({e}), using default")
    return _build_default_state()


def _save_state(state: dict) -> None:
    _AUDIT.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_STATE)


def _build_default_state() -> dict:
    cfg = _load_config()
    return {
        "schema_version": 1,
        "status": "running",
        "cycle": 0,
        "active_task": None,
        "last_advance": _now(),
        "last_checkpoint": None,
        "rate_limit_wait": _RATE_WAIT_INIT,
        "tasks": cfg.get("tasks", []),
        "updated_at": _now(),
        "mission_start": _now(),
    }


def _load_config() -> dict:
    cfg = _TOOLS / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))
        except Exception as e:
            _log(f"WARN: config.json unreadable: {e}")
    return {}


def _is_rate_limited(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in _RATE_PATTERNS)


def _past_deadline() -> bool:
    return datetime.now(tz=timezone.utc) >= _DEADLINE


def _stop_requested() -> bool:
    return _STOP.exists() or _past_deadline()


# ── Instance lock (Windows-compatible PID file) ────────────────────────────────

def _acquire_lock() -> bool:
    if _LOCK.exists():
        try:
            pid = int(_LOCK.read_text().strip())
            # OpenProcess with SYNCHRONIZE (0x100000) to check if alive
            import ctypes
            SYNCHRONIZE = 0x100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                _log(f"ERROR: Another instance already running (PID {pid})")
                return False
        except Exception:
            pass  # stale lock
    _LOCK.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        _LOCK.unlink(missing_ok=True)
    except Exception:
        pass


# ── Task selection ─────────────────────────────────────────────────────────────

def _next_task(state: dict) -> dict | None:
    done_ids = {t["id"] for t in state["tasks"] if t.get("status") == "done"}
    for task in state["tasks"]:
        if task.get("status") not in ("pending",):
            continue
        deps = task.get("dependencies", [])
        if all(d in done_ids for d in deps):
            return task
    return None


# ── Claude session runner ──────────────────────────────────────────────────────

def _build_prompt(task: dict, state: dict) -> str:
    """Assemble the full prompt: checkpoint preamble + task body."""
    prompt_file = _TOOLS / "prompts" / f"{task['id']}.txt"
    if prompt_file.exists():
        body = prompt_file.read_text(encoding="utf-8")
    else:
        body = task.get("prompt", f"[No prompt for {task['id']}]")

    preamble = f"""# ContentEngine Weekend Mission — Autonomous Session
Timestamp: {_now()}
Cycle: {state.get('cycle', 0)}
Task: {task['id']} — {task['name']} (attempt {task.get('attempts', 0) + 1}/{task.get('max_attempts', 3)})

IMPORTANT — before starting:
1. Read CLAUDE.md for project rules (already in context if run from ContentEngine/)
2. Read audits/weekend_stability/MISSION_STATE.json for current state
3. Read audits/weekend_stability/PROGRESS.md for what was already done
4. Read audits/weekend_stability/NEXT_ACTION.md for what was planned next

IMPORTANT — when done:
- Append findings to audits/weekend_stability/PROGRESS.md
- Update audits/weekend_stability/MISSION_STATE.json: set task '{task['id']}' status to 'done'
- Write audits/weekend_stability/NEXT_ACTION.md with the next logical step

CONSTRAINTS:
- Do NOT delete clips, jobs, videos, packages, or publications
- Do NOT run destructive DB migrations
- Do NOT modify historical job records
- Do NOT publish to social platforms
- Do NOT bypass Windows security or install global packages
- Commit code changes with git when relevant

---
{body}
"""
    return preamble


def _run_session(prompt: str, task: dict) -> tuple[int, str]:
    """Run `claude --print --dangerously-skip-permissions` and return (exit_code, output)."""
    timeout = task.get("timeout_s", 1800)
    cmd = [
        "claude", "--print",
        "--permission-mode", "auto",
        "--output-format", "text",
        "--add-dir", str(_ROOT),
    ]
    _log(f"  Launching claude --print for '{task['id']}' (timeout={timeout}s)")
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(_ROOT),
        )
        combined = result.stdout + ("\n[stderr]\n" + result.stderr if result.stderr.strip() else "")
        return result.returncode, combined
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return 124, f"TIMEOUT after {timeout}s\n{out}"
    except FileNotFoundError:
        return 127, "ERROR: 'claude' not found in PATH. Is Claude Code installed?"
    except Exception as exc:
        return 1, f"ERROR launching claude: {exc}"


# ── Main loop ──────────────────────────────────────────────────────────────────

def run(test_mode: bool = False) -> None:
    _AUDIT.mkdir(parents=True, exist_ok=True)
    (_TOOLS / "prompts").mkdir(parents=True, exist_ok=True)

    if not _acquire_lock():
        sys.exit(1)

    _STOP.unlink(missing_ok=True)  # clear any stale stop signal

    state = _load_state()
    rate_wait = state.get("rate_limit_wait", _RATE_WAIT_INIT)

    # Recovery: reset any tasks that were "running" when the previous session died
    recovered = []
    for task in state["tasks"]:
        if task.get("status") == "running":
            task["status"] = "pending"
            recovered.append(task["id"])
    if recovered:
        _log(f"  Recovered interrupted tasks from previous session: {recovered}")
        _save_state(state)

    _log(f"Supervisor started. PID={os.getpid()} cycle={state['cycle']} mode={'TEST' if test_mode else 'NORMAL'}")

    try:
        while not _stop_requested():
            task = _next_task(state)
            if task is None:
                pending = [t for t in state["tasks"] if t.get("status") == "pending"]
                if pending:
                    _log("All ready tasks blocked or done. Remaining tasks have unmet dependencies.")
                else:
                    _log("All tasks completed.")
                state["status"] = "completed"
                _save_state(state)
                break

            state["cycle"] += 1
            state["active_task"] = task["id"]
            task["status"] = "running"
            task["attempts"] = task.get("attempts", 0) + 1
            state["updated_at"] = _now()
            _save_state(state)

            _log(f"Cycle {state['cycle']}: task='{task['id']}' attempt={task['attempts']}/{task.get('max_attempts',3)}")

            prompt = _build_prompt(task, state)
            exit_code, output = _run_session(prompt, task)

            # Save raw output (capped)
            out_file = _AUDIT / f"output_{task['id']}_c{state['cycle']:03d}.txt"
            out_file.write_text(output[:200_000], encoding="utf-8", errors="replace")
            _log(f"  exit={exit_code} len={len(output):,} → {out_file.name}")

            tail = output[-3000:]  # last 3K chars for pattern matching

            if exit_code == 127:
                _log("FATAL: claude not in PATH. Cannot continue.")
                state["status"] = "blocked"
                state["active_task"] = None
                _save_state(state)
                break

            if _is_rate_limited(tail):
                task["status"] = "pending"
                task["attempts"] = max(0, task.get("attempts", 1) - 1)  # don't count rate-limited runs
                next_wait = min(rate_wait * _RATE_WAIT_MULT, _RATE_WAIT_MAX)
                _log(f"  Rate limited. Waiting {rate_wait}s (next: {next_wait}s)")
                state["rate_limit_wait"] = next_wait
                state["active_task"] = None
                _save_state(state)
                time.sleep(rate_wait)
                rate_wait = next_wait
                continue

            if exit_code == 0:
                task["status"] = "done"
                task["completed_at"] = _now()
                state["last_advance"] = _now()
                state["last_checkpoint"] = task["id"]
                rate_wait = _RATE_WAIT_INIT  # reset backoff on success
                _log(f"  Task '{task['id']}' DONE.")
            elif task["attempts"] >= task.get("max_attempts", 3):
                task["status"] = "blocked"
                _log(f"  Task '{task['id']}' BLOCKED (max attempts reached).")
                state["last_checkpoint"] = f"blocked_{task['id']}"
            else:
                task["status"] = "pending"
                _log(f"  Task '{task['id']}' FAILED (exit={exit_code}), will retry.")

            state["active_task"] = None
            state["updated_at"] = _now()
            _save_state(state)

            if test_mode:
                _log("Test mode: first cycle done. Exiting.")
                break

            time.sleep(10)  # brief pause between tasks

    except KeyboardInterrupt:
        _log("KeyboardInterrupt — stopping cleanly.")
    except Exception as exc:
        _log(f"UNEXPECTED ERROR: {exc}")
        import traceback
        _log(traceback.format_exc())
    finally:
        state["status"] = "stopped"
        state["active_task"] = None
        state["updated_at"] = _now()
        _save_state(state)
        _release_lock()
        _log("Supervisor stopped.")


def print_status() -> None:
    state = _load_state()
    print(json.dumps(state, indent=2, ensure_ascii=False))
    # Summary line
    tasks = state.get("tasks", [])
    by_status: dict[str, int] = {}
    for t in tasks:
        s = t.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
    print(f"\nTasks: {by_status}")
    if _LOCK.exists():
        print(f"Running: PID {_LOCK.read_text().strip()}")
    else:
        print("Not running (no lock file).")


def main() -> None:
    args = sys.argv[1:]
    if "--status" in args:
        print_status()
    elif "--test" in args:
        run(test_mode=True)
    else:
        run(test_mode=False)


if __name__ == "__main__":
    main()
