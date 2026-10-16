import asyncio

import pytest

from app.services.streaming.worker import ChunkWorker, Turn


@pytest.mark.asyncio
async def test_turns_are_handled_in_submission_order():
    seen = []

    async def handle(turn):
        await asyncio.sleep(0.001)
        seen.append(turn.text)

    worker = ChunkWorker(handle)
    worker.start()
    for text in ["one", "two", "three"]:
        worker.submit(Turn(text))
    assert await worker.drain(timeout=2)
    assert seen == ["one", "two", "three"]
    await worker.cancel()


@pytest.mark.asyncio
async def test_drain_reports_timeout_when_a_turn_is_stuck():
    never = asyncio.Event()

    async def handle(turn):
        await never.wait()

    worker = ChunkWorker(handle)
    worker.start()
    worker.submit(Turn("stuck"))
    assert await worker.drain(timeout=0.05) is False


@pytest.mark.asyncio
async def test_cancel_counts_in_flight_and_queued_turns():
    never = asyncio.Event()

    async def handle(turn):
        await never.wait()

    worker = ChunkWorker(handle)
    worker.start()
    for text in ["a", "b", "c"]:
        worker.submit(Turn(text))
    await asyncio.sleep(0)  # let the worker pick up the first turn
    assert await worker.cancel() == 3


@pytest.mark.asyncio
async def test_a_failing_turn_does_not_stop_later_turns():
    seen = []

    async def handle(turn):
        if turn.text == "bad":
            raise RuntimeError("boom")
        seen.append(turn.text)

    worker = ChunkWorker(handle)
    worker.start()
    for text in ["good", "bad", "after"]:
        worker.submit(Turn(text))
    assert await worker.drain(timeout=2)
    assert seen == ["good", "after"]
    await worker.cancel()
