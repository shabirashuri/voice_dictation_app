"""Processes one dictation session's final transcript turns, in order.

The AssemblyAI event callback must stay fast: while it waits on an LLM call,
no further events (including partial transcripts) are delivered. The callback
therefore only enqueues final turns here; this worker handles them one by one.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Turn:
    text: str
    # Per-session id shown to the client; lets it link a line to its status.
    turn_id: int = 0


class ChunkWorker:
    def __init__(self, handle: Callable[[Turn], Awaitable[None]]):
        self._handle = handle
        self._queue: asyncio.Queue[Turn] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._busy = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="chunk-worker")

    def submit(self, turn: Turn) -> None:
        self._queue.put_nowait(turn)

    async def drain(self, timeout: float) -> bool:
        """Wait until every submitted turn has been handled. False on timeout."""
        try:
            await asyncio.wait_for(self._queue.join(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def cancel(self) -> int:
        """Stop the worker. Returns how many turns were abandoned (in-flight + queued)."""
        abandoned = self._queue.qsize() + (1 if self._busy else 0)
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return abandoned

    async def _run(self) -> None:
        while True:
            turn = await self._queue.get()
            self._busy = True
            try:
                await self._handle(turn)
            except Exception:
                # One bad turn must not stop the rest of the dictation.
                logger.exception("chunk handler failed")
            finally:
                self._busy = False
                self._queue.task_done()
