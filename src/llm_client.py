"""One shared Anthropic client for the interpreter and the renderer.

Why this exists:
- Two separate clients meant two separate connection pools.
- The SDK's default keepalive expiry is 5 seconds. Between turns (her line plus
  the learner's line) the pooled connection usually expired, so every turn paid
  for a fresh TCP + TLS handshake before the interpreter call even started.
- warm() re-opens the connection while the learner is still talking, so it is
  already open when the turn ends. It uses the models endpoint, which costs no
  tokens.
"""

import asyncio
import os
import time

import anthropic

from tracing import mark

KEEPALIVE_S = float(os.environ.get("ANTHROPIC_KEEPALIVE_S", "60"))
WARM_IF_IDLE_S = float(os.environ.get("ANTHROPIC_WARM_IF_IDLE_S", "4"))


def _build_http_client():
    # The SDK has moved between httpx packages across versions, so build the
    # Limits object from the same class the SDK itself uses instead of
    # importing httpx directly.
    try:
        from anthropic._constants import DEFAULT_CONNECTION_LIMITS as defaults

        limits = type(defaults)(
            max_connections=defaults.max_connections,
            max_keepalive_connections=defaults.max_keepalive_connections,
            keepalive_expiry=KEEPALIVE_S,
        )
        return anthropic.DefaultAsyncHttpxClient(limits=limits)
    except Exception as e:  # degrade quietly: default pool, warm() still helps
        mark("llm_client", "keepalive not set", repr(e))
        return None


_http_client = _build_http_client()
client = anthropic.AsyncAnthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    **({"http_client": _http_client} if _http_client is not None else {}),
)

_last_activity = 0.0
_warm_task: asyncio.Task | None = None


def touch():
    """Record that a request just used the connection."""
    global _last_activity
    _last_activity = time.monotonic()


async def _warm():
    t0 = time.monotonic()
    try:
        await client.models.list(limit=1)
        mark("llm_client", "warm ok", f"{(time.monotonic() - t0) * 1000:.0f}ms")
    except Exception as e:
        mark("llm_client", "warm failed", repr(e))


def warm():
    """Fire-and-forget. Skips if the connection was used recently or a warm-up is running."""
    global _warm_task
    if time.monotonic() - _last_activity < WARM_IF_IDLE_S:
        return
    if _warm_task is not None and not _warm_task.done():
        return
    touch()
    _warm_task = asyncio.create_task(_warm())
