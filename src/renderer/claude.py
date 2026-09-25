import os

import anthropic

from renderer.prompt import RENDERER_TASK_PROMPT

client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

RENDERER_MODEL = os.environ.get("RENDERER_MODEL", "claude-haiku-4-5-20251001")

import re

SENTENCE_END = re.compile(r"[.!?]\s")

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
            match = m

        if match:
            split_at = match.end()
            yield buffer[:split_at].strip()
            buffer = buffer[split_at:]

    if buffer.strip():
        yield buffer.strip()

async def _raw_token_stream(message: str):
    async with client.messages.stream(
        model=RENDERER_MODEL,
        max_tokens=150,
        thinking={"type": "disabled"},
        system=[{"type": "text", "text": RENDERER_TASK_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": message}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def stream_renderer(message: str):
    async for chunk in aggregate_renderer_stream(_raw_token_stream(message)):
        yield chunk

async def call_renderer(message: str) -> str:
    return " ".join([chunk async for chunk in stream_renderer(message)])