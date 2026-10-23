"""Exceptions for the Concat adapter. All are non-fatal — callers must fall back to FFmpeg."""


class ConcatNotAvailable(RuntimeError):
    """Concat is not installed, not enabled, or blocked by Windows security."""


class ConcatTimeout(RuntimeError):
    """An MCP operation or export exceeded its configured timeout."""


class ConcatMCPError(RuntimeError):
    """The MCP server returned a JSON-RPC error response."""
    def __init__(self, message: str, code: int = -1, data=None):
        super().__init__(message)
        self.code = code
        self.data = data


class ConcatExportFailed(RuntimeError):
    """Export completed but the output file is missing or invalid."""
