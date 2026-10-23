"""Concat integration — experimental secondary render engine.

Feature flag: ``CONFIG.concat_enabled``  (default: False)

Only import from this package after checking availability:

    from integrations.concat import get_adapter, concat_available
    if concat_available():
        adapter = get_adapter()
        result = adapter.render(req)
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from integrations.concat.exceptions import ConcatNotAvailable

_adapter_instance = None


def concat_available() -> bool:
    """Return True if Concat is enabled in config AND the executable exists."""
    try:
        from engine.config import CONFIG
        if not CONFIG.concat_enabled:
            return False
        from integrations.concat.adapter import ConcatAdapter
        return ConcatAdapter(CONFIG.concat_exe_path, CONFIG.concat_projects_dir).is_available()
    except Exception:
        return False


def get_adapter():
    """Return a ConcatAdapter configured from CONFIG. Raises ConcatNotAvailable if unavailable."""
    from engine.config import CONFIG
    if not CONFIG.concat_enabled:
        raise ConcatNotAvailable("Concat is disabled (concat_enabled=False in config)")
    from integrations.concat.adapter import ConcatAdapter
    return ConcatAdapter(
        exe_path=CONFIG.concat_exe_path,
        projects_dir=CONFIG.concat_projects_dir,
        mcp_timeout_s=CONFIG.concat_mcp_timeout_s,
        export_timeout_s=CONFIG.concat_export_timeout_s,
    )


def get_availability_status() -> dict:
    """Return a status dict for the API/dashboard availability endpoint."""
    from engine.config import CONFIG
    from pathlib import Path

    status = {
        "enabled": CONFIG.concat_enabled,
        "exe_configured": CONFIG.concat_exe_path,
        "exe_exists": Path(CONFIG.concat_exe_path).exists(),
        "available": False,
        "version": None,
        "error": None,
    }

    if not CONFIG.concat_enabled:
        status["error"] = "Disabled — set concat_enabled=True in config to activate"
        return status

    if not status["exe_exists"]:
        status["error"] = f"Executable not found: {CONFIG.concat_exe_path}"
        return status

    try:
        from integrations.concat.adapter import ConcatAdapter
        adapter = ConcatAdapter(CONFIG.concat_exe_path, CONFIG.concat_projects_dir,
                                mcp_timeout_s=10.0)
        if adapter.is_available():
            status["available"] = True
            status["version"] = "0.2.8"
        else:
            status["error"] = "Executable found but failed to respond (possible SAC block)"
    except ConcatNotAvailable as e:
        status["error"] = str(e)
    except Exception as e:
        status["error"] = f"Unexpected error: {e}"

    return status
