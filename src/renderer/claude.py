import os
import re

import anthropic

from renderer.prompt import RENDERER_TASK_PROMPT
from tracing import mark

client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

RENDERER_MODEL = os.environ.get("RENDERER_MODEL", "claude-haiku-4-5-20251001")

SENTENCE_END = re.compile(r"(?<!\.)[.!?](?!\.)\s")
MIN_CHUNK_CHARS = 25


async def aggregate_renderer_stream(text_stream):
    buffer = ""
    open_brackets = 0

    async for token in text_stream:
        buffer += token
        open_brackets += token.count("[") - token.count("]")

        if open_brackets != 0:
            continue

        match = None
        for m in SENTENCE_END.finditer(buffer):
            if m.end() >= MIN_CHUNK_CHARS:
                match = m

        if match:
            yield buffer[:match.end()].strip()
            buffer = buffer[match.end():]

    if buffer.strip():
        yield buffer.strip()


async def _raw_token_stream(message: str):
    first = True
    async with client.messages.stream(
        model=RENDERER_MODEL,
        max_tokens=150,
        thinking={"type": "disabled"},
        system=[{"type": "text", "text": RENDERER_TASK_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": message}],
    ) as stream:
        async for text in stream.text_stream:
            if first:
                mark("renderer", "first token <-", repr(text), key="render_first_token")
                first = False
            yield text


async def stream_renderer(message: str):
    async for chunk in aggregate_renderer_stream(_raw_token_stream(message)):
        yield chunk


async def call_renderer(message: str) -> str:
    return " ".join([chunk async for chunk in stream_renderer(message)])