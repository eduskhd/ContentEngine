"""JSON-RPC 2.0 client for concat-cli api mode.

concat-cli is launched as a subprocess; a batch of JSON-RPC requests is fed
to stdin and all responses (plus export events) are read from stdout.

This replaces the MCP protocol used in mcp_client.py.  The concat-cli binary
exposes the same underlying Concat API as the MCP server, just via a simpler
transport (one JSON object per line, no tools/call envelope).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from integrations.concat.exceptions import ConcatMCPError, ConcatNotAvailable, ConcatTimeout

logger = logging.getLogger("concat.api")

# DLLs that concat-cli needs at runtime on Windows
_RUNTIME_PATHS = [
    r"C:\Users\edupo\Desktop\ffmpeg-dev\bin",
    r"C:\Program Files\LLVM\bin",
]


class APIClient:
    """Executes a batch of JSON-RPC requests against concat-cli api.

    Each ``run_batch`` call launches one subprocess, feeds all requests to
    stdin, and collects all responses + events from stdout.  Export jobs are
    handled by making ``export.run`` the last request: concat-cli waits for
    the job to finish before exiting, emitting progress/done/failed events
    on stdout as they happen.
    """

    def __init__(self, cli_path: str, timeout_s: float = 600.0):
        self._cli = cli_path
        self._timeout = timeout_s

    def run_batch(self, requests: list[dict]) -> dict[str | int, Any]:
        """Run requests; return {id: full_msg} plus ``_events`` list."""
        if not Path(self._cli).exists():
            raise ConcatNotAvailable(f"concat-cli not found: {self._cli}")

        input_str = "\n".join(json.dumps(r) for r in requests) + "\n"

        try:
            proc = subprocess.run(
                [self._cli, "api"],
                input=input_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_build_env(),
            )
        except subprocess.TimeoutExpired:
            raise ConcatTimeout(f"concat-cli timed out after {self._timeout}s")
        except OSError as exc:
            raise ConcatNotAvailable(f"Failed to launch concat-cli: {exc}") from exc

        if proc.returncode != 0 and not proc.stdout.strip():
            raise ConcatMCPError(
                f"concat-cli exited {proc.returncode}: {proc.stderr[:400]}"
            )

        responses: dict[str | int, Any] = {}
        events: list[dict] = []

        for raw in proc.stdout.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("concat-cli non-JSON stdout: %s", raw[:200])
                continue

            if msg.get("id") is not None:
                responses[msg["id"]] = msg
            elif msg.get("method"):
                events.append(msg)

        responses["_events"] = events
        return responses

    def call(self, method: str, params: dict) -> Any:
        """Single-call convenience method.  Raises on API error."""
        results = self.run_batch([
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ])
        msg = results.get(1)
        if not msg:
            raise ConcatMCPError(f"No response to {method}")
        if "error" in msg:
            raise ConcatMCPError(msg["error"].get("message", str(msg["error"])))
        return msg.get("result")


def _extract_result(responses: dict, req_id: int, method: str = "") -> Any:
    """Return result dict or raise ConcatMCPError."""
    msg = responses.get(req_id)
    if not msg:
        raise ConcatMCPError(f"No response for id={req_id} ({method})")
    if "error" in msg:
        err = msg["error"]
        raise ConcatMCPError(
            err.get("message", f"API error for {method}"),
            code=err.get("code", -1),
            data=err.get("data"),
        )
    return msg.get("result", {})


def _build_env() -> dict:
    """Return os.environ copy with FFmpeg + LLVM DLL directories on PATH."""
    env = os.environ.copy()
    current = env.get("PATH", "")
    additions = [p for p in _RUNTIME_PATHS if p not in current and Path(p).exists()]
    if additions:
        env["PATH"] = current + ";" + ";".join(additions)
    return env
