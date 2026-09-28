"""Speculative rendering, kept free of Pipecat so it can be unit tested.

The renderer starts on a predicted message (the state the turn would produce
with no flags) while the interpreter is still running. Its chunks are held back.
When the real message is known:
- identical: the held chunks are released and the stream continues (a hit)
- different: the speculative stream is cancelled and a new one starts (a miss)

Nothing reaches TTS unless it was generated from the rule-derived state, so the
rules still decide. A hit hides the interpreter's latency; a miss costs about
what the old serial path cost.
"""

import asyncio
from typing import AsyncIterator, Awaitable, Callable


async def _collect(stream_fn, message: str, queue: asyncio.Queue):
    try:
        async for chunk in stream_fn(message):
            await queue.put(("chunk", chunk))
        await queue.put(("done", None))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await queue.put(("error", e))


async def speculative_render(
    spec_message: str,
    real_message: Awaitable[str],
    stream_fn: Callable[[str], AsyncIterator[str]],
    emit: Callable[[str], Awaitable[None]],
) -> tuple[str, bool]:
    """Returns (full line, whether the speculative start was used)."""
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_collect(stream_fn, spec_message, queue))

    try:
        final_message = await real_message
    except BaseException:
        task.cancel()
        raise

    hit = final_message == spec_message
    if not hit:
        task.cancel()
        queue = asyncio.Queue()
        task = asyncio.create_task(_collect(stream_fn, final_message, queue))

    parts: list[str] = []
    try:
        while True:
            kind, value = await queue.get()
            if kind == "done":
                break
            if kind == "error":
                raise value
            parts.append(value)
            await emit(value)
    finally:
        if not task.done():
            task.cancel()

    return " ".join(parts), hit
