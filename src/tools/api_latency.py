"""How much of each Claude call is network and handshake, and how much is the model?

    python tools/api_latency.py            # idle gap 10s
    python tools/api_latency.py --idle=20

Runs, against the same model the interpreter uses:
  1. a cold call on a brand-new client (includes TCP + TLS setup)
  2. three back-to-back warm calls (connection already open)
  3. a call after sitting idle, with the SDK's default 5s keepalive
  4. a call after sitting idle, with the shared client (60s keepalive)
  5. the models endpoint (no tokens, pure round trip)

Each messages call asks for 1 output token, so the time is almost all network
plus time to first token. Costs a fraction of a cent in total.
"""

import asyncio
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import anthropic

from interpreter.claude import INTERPRETER_MODEL
from llm_client import client as shared_client


async def one_token(client) -> float:
    t0 = time.monotonic()
    await client.messages.create(
        model=INTERPRETER_MODEL,
        max_tokens=1,
        messages=[{"role": "user", "content": "Say ok."}],
    )
    return time.monotonic() - t0


async def models_ping(client) -> float:
    t0 = time.monotonic()
    await client.models.list(limit=1)
    return time.monotonic() - t0


async def main(idle_s: float):
    default_client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    print(f"model: {INTERPRETER_MODEL}\n")
    print(f"cold (new client, default pool)   {await one_token(default_client) * 1000:6.0f}ms")
    for i in range(3):
        print(f"warm #{i + 1}                           {await one_token(default_client) * 1000:6.0f}ms")
    print(f"models endpoint, warm             {await models_ping(default_client) * 1000:6.0f}ms")

    await one_token(shared_client)  # open the shared client's connection
    print(f"\nidling {idle_s:.0f}s...")
    await asyncio.sleep(idle_s)
    default_idle = await one_token(default_client)
    shared_idle = await one_token(shared_client)
    print(f"after idle, default 5s keepalive  {default_idle * 1000:6.0f}ms")
    print(f"after idle, shared 60s keepalive  {shared_idle * 1000:6.0f}ms")
    print(
        "\nIf 'after idle, default' is close to 'cold' and the shared one is close to 'warm',"
        "\nthe keepalive change is saving that difference on every turn."
        "\nIf 'warm' itself is large, most of the interpreter time is network, not the model."
    )


if __name__ == "__main__":
    idle = 10.0
    for arg in sys.argv[1:]:
        if arg.startswith("--idle="):
            idle = float(arg.split("=", 1)[1])
    asyncio.run(main(idle))
