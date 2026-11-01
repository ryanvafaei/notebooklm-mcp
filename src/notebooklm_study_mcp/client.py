"""Lazy, single-flight ownership of the process-wide NotebookLM client.

Why lazy: Claude Desktop gives the MCP ``initialize`` handshake a short deadline.
Opening the client means a round-trip to Google (cookie check + CSRF fetch), so it
must not block startup. The server starts instantly; the client opens on the first
tool call, and a failure there becomes a readable tool error (e.g. "run notebooklm
login") instead of a server that silently vanishes from Claude.

Failures are not cached: after you re-run ``notebooklm login`` the next tool call
retries, so no Claude restart is needed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

logger = logging.getLogger(__name__)

ClientFactory = Callable[[], AbstractAsyncContextManager[Any]]


def default_factory() -> AbstractAsyncContextManager[Any]:
    """Open a NotebookLM client from the locally stored login (``notebooklm login``)."""
    from notebooklm import NotebookLMClient

    return NotebookLMClient.from_storage(keepalive=600.0)  # type: ignore[return-value]


class ClientProvider:
    """Owns one lazily-opened client; concurrent callers share a single open."""

    def __init__(self, factory: ClientFactory = default_factory) -> None:
        self._factory = factory
        self._cm: AbstractAsyncContextManager[Any] | None = None
        self._client: Any = None
        self._open_task: asyncio.Task[Any] | None = None
        self._closed = False

    @property
    def is_open(self) -> bool:
        return self._client is not None

    async def get(self) -> Any:
        if self._client is not None:
            return self._client
        if self._closed:
            raise RuntimeError("The server is shutting down.")
        task = self._open_task
        if task is None or task.done():
            task = asyncio.ensure_future(self._open())
            task.add_done_callback(self._on_done)
            self._open_task = task
        # shield: one caller timing out must not cancel the open others are awaiting.
        return await asyncio.shield(task)

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled() or task.exception() is not None:
            if self._open_task is task:
                self._open_task = None  # retry on next call instead of caching failure

    async def _open(self) -> Any:
        cm = self._factory()
        client = await cm.__aenter__()
        if self._closed:
            await cm.__aexit__(None, None, None)
            raise RuntimeError("The server is shutting down.")
        self._cm, self._client = cm, client
        logger.info("NotebookLM client opened")
        return client

    async def aclose(self) -> None:
        self._closed = True
        task, self._open_task = self._open_task, None
        if task is not None and not task.done():
            task.cancel()
        cm, self._cm, self._client = self._cm, None, None
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.warning("Error closing NotebookLM client: %s", type(exc).__name__)
