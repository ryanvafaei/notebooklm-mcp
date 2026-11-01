"""Translate library exceptions into short, safe, actionable tool errors.

Raw exceptions can carry snippets of Google's responses, file paths or token-like
strings. Everything that reaches Claude goes through :func:`to_tool_error`, which
picks a fixed message per error category and scrubs whatever detail it keeps.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Awaitable, Callable

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

LOGIN_HINT = (
    "NotebookLM is not logged in, or the saved Google session has expired. "
    "In a terminal, cd into the notebooklm-mcp folder and run:  uv run notebooklm login  "
    "then simply retry (no Claude restart needed)."
)

_TOKENISH = re.compile(r"[A-Za-z0-9_\-]{32,}")
_PATHISH = re.compile(r"(?:[A-Za-z]:)?[\\/](?:[^\s\\/:'\"]+[\\/])+[^\s\\/:'\"]*")
_MAX_DETAIL = 300


def scrub(text: str) -> str:
    """Remove token-like strings and file paths, and cap the length."""
    text = _TOKENISH.sub("[redacted]", text)
    text = _PATHISH.sub("[path]", text)
    return text[:_MAX_DETAIL]


def to_tool_error(exc: BaseException) -> ToolError:
    """Map any exception to a ToolError whose message is safe to show Claude."""
    import notebooklm as nlm

    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, FileNotFoundError | nlm.AuthError):
        return ToolError(LOGIN_HINT)
    if isinstance(exc, nlm.RateLimitError):
        return ToolError(
            "NotebookLM rate limit or daily quota reached. Wait a while and try again."
        )
    if isinstance(exc, nlm.NotFoundError):
        return ToolError(
            "Not found. Check the ID (use list_notebooks / get_notebook / list_artifacts "
            f"to find valid IDs). Detail: {scrub(str(exc))}"
        )
    if isinstance(exc, nlm.ValidationError):
        return ToolError(f"Invalid request: {scrub(str(exc))}")
    if isinstance(exc, nlm.WaitTimeoutError | TimeoutError):
        return ToolError(
            "Timed out waiting for NotebookLM. The job may still finish; check again shortly."
        )
    if isinstance(exc, nlm.NetworkError):
        return ToolError("Network error talking to NotebookLM. Check your connection and retry.")
    if isinstance(exc, nlm.NotebookLMError):
        return ToolError(f"NotebookLM error ({type(exc).__name__}): {scrub(str(exc))}")
    if isinstance(exc, ValueError):
        return ToolError(scrub(str(exc)))
    return ToolError(f"Unexpected error ({type(exc).__name__}). See the server log for details.")


def handle_errors[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Decorator: convert exceptions raised by a tool into safe ToolErrors."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as exc:
            # Log only the type: messages can contain response snippets.
            logger.warning("Tool %s failed: %s", fn.__name__, type(exc).__name__)
            raise to_tool_error(exc) from None

    return wrapper
