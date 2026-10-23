"""MCP stdio JSON-RPC 2.0 client for Concat v0.2.8.

Concat is launched as a subprocess with ``--mcp headless``.  Communication is
newline-delimited JSON-RPC 2.0 over stdin/stdout.  Each call blocks until the
response arrives or the timeout fires.

One MCPClient instance manages ONE Concat process.  For parallel renders, each
worker must create its own instance with a separate project directory.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from integrations.concat.exceptions import ConcatMCPError, ConcatNotAvailable, ConcatTimeout

logger = logging.getLogger("concat.mcp")

_INIT_TIMEOUT_S = 15.0  # seconds to wait for MCP server to start


class MCPClient:
    """Manages one ``concat --mcp headless`` process via stdin/stdout JSON-RPC."""

    def __init__(self, exe_path: str, timeout_s: float = 60.0):
        self._exe = exe_path
        self._timeout = timeout_s
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the Concat MCP process. Raises ConcatNotAvailable if it fails."""
        if not Path(self._exe).exists():
            raise ConcatNotAvailable(f"Concat executable not found: {self._exe}")
        try:
            self._proc = subprocess.Popen(
                [self._exe, "--mcp", "headless"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            # Windows Smart App Control or permission error
            raise ConcatNotAvailable(f"Failed to launch Concat: {exc}") from exc

        # Wait for the server to emit its initialization JSON
        deadline = time.monotonic() + _INIT_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                stderr_out = self._proc.stderr.read(2000) if self._proc.stderr else ""
                raise ConcatNotAvailable(
                    f"Concat process exited immediately (rc={self._proc.returncode}). "
                    f"stderr: {stderr_out}"
                )
            # The MCP server writes an initialization message on startup
            line = self._readline_nonblock()
            if line:
                try:
                    msg = json.loads(line)
                    if msg.get("jsonrpc") or msg.get("result") or msg.get("method"):
                        logger.debug("Concat MCP ready: %s", line[:120])
                        return
                except json.JSONDecodeError:
                    pass
            time.sleep(0.1)
        raise ConcatNotAvailable("Concat MCP did not start within timeout")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    # ── public API ───────────────────────────────────────────────────────────

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a Concat MCP tool. Returns the parsed result or raises."""
        with self._lock:
            return self._call_locked(tool, arguments or {})

    def get_version(self) -> str:
        result = self.call("concat_version")
        return result.get("version", "unknown") if isinstance(result, dict) else str(result)

    # ── internals ────────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _call_locked(self, tool: str, arguments: dict) -> Any:
        if not self._proc or self._proc.poll() is not None:
            raise ConcatNotAvailable("Concat process is not running")

        req_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        line = json.dumps(request) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except OSError as exc:
            raise ConcatMCPError(f"Failed to write to Concat stdin: {exc}") from exc

        return self._read_response(req_id)

    def _read_response(self, expected_id: int) -> Any:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise ConcatNotAvailable("Concat process died while waiting for response")
            raw = self._readline_nonblock()
            if not raw:
                time.sleep(0.05)
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Concat non-JSON stdout: %s", raw[:200])
                continue
            if msg.get("id") != expected_id:
                logger.debug("Concat out-of-order message id=%s (expected %s)", msg.get("id"), expected_id)
                continue
            if "error" in msg:
                err = msg["error"]
                raise ConcatMCPError(
                    err.get("message", "Unknown MCP error"),
                    code=err.get("code", -1),
                    data=err.get("data"),
                )
            # MCP wraps tool results in content[0].text
            result = msg.get("result", {})
            if isinstance(result, dict):
                content = result.get("content", [])
                if content and isinstance(content[0], dict) and content[0].get("type") == "text":
                    try:
                        return json.loads(content[0]["text"])
                    except (json.JSONDecodeError, KeyError):
                        return content[0].get("text")
            return result
        raise ConcatTimeout(f"Concat tool '{expected_id}' timed out after {self._timeout}s")

    def _readline_nonblock(self) -> str:
        """Read one line from stdout without blocking; returns '' if nothing available."""
        import select as _select
        import sys as _sys
        if _sys.platform == "win32":
            # On Windows, select() doesn't work on pipes — use a background reader thread
            if not hasattr(self, "_stdout_lines"):
                self._stdout_lines: list[str] = []
                self._reader_thread = threading.Thread(
                    target=self._stdout_reader, daemon=True
                )
                self._reader_thread.start()
            if self._stdout_lines:
                return self._stdout_lines.pop(0)
            return ""
        # POSIX: use select
        rlist, _, _ = _select.select([self._proc.stdout], [], [], 0)
        if rlist:
            return self._proc.stdout.readline()
        return ""

    def _stdout_reader(self) -> None:
        """Background thread: reads lines from Concat stdout into a buffer."""
        try:
            for line in self._proc.stdout:
                self._stdout_lines.append(line.rstrip("\n"))
        except Exception:
            pass
