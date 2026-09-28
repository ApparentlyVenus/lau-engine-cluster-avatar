import os
import re

from llm_client import client, touch
from renderer.prompt import RENDERER_TASK_PROMPT
from tracing import mark

RENDERER_MODEL = os.environ.get("RENDERER_MODEL", "claude-haiku-4-5-20251001")

SENTENCE_END = re.compile(r"(?<!\.)[.!?](?!\.)\s")
# The first chunk may also end at a clause boundary, so TTS can start before the
# first sentence is finished. Hyphens are excluded on purpose: "Wait- what" is a
# self-interruption and should stay in one piece. Ellipses stay excluded too.
CLAUSE_END = re.compile(r"(?<!\.)[.!?,;:](?!\.)\s|\s[\u2014\u2013]\s")
TAG = re.compile(r"\[[^\]]*\]")

MIN_CHUNK_CHARS = 25
FIRST_CHUNK_MIN_SPOKEN_CHARS = 12
EARLY_FIRST_CHUNK = os.environ.get("EARLY_FIRST_CHUNK", "1") != "0"


def _spoken_len(text: str) -> int:
    return len(TAG.sub("", text).strip())


async def aggregate_renderer_stream(text_stream, early_first_chunk: bool = EARLY_FIRST_CHUNK):
    buffer = ""
    open_brackets = 0
    first = early_first_chunk

    async for token in text_stream:
        buffer += token
        open_brackets += token.count("[") - token.count("]")

        if open_brackets != 0:
            continue

        match = None
        if first:
            for m in CLAUSE_END.finditer(buffer):
                if _spoken_len(buffer[:m.end()]) >= FIRST_CHUNK_MIN_SPOKEN_CHARS:
                    match = m
                    break
        else:
            for m in SENTENCE_END.finditer(buffer):
                if m.end() >= MIN_CHUNK_CHARS:
                    match = m

        if match:
            first = False
            yield buffer[:match.end()].strip()
            buffer = buffer[match.end():]

    if buffer.strip():
        yield buffer.strip()


async def _raw_token_stream(message: str):
    first = True
    touch()
    try:
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
    finally:
        touch()


async def stream_renderer(message: str):
    async for chunk in aggregate_renderer_stream(_raw_token_stream(message)):
        yield chunk


async def call_renderer(message: str) -> str:
    return " ".join([chunk async for chunk in stream_renderer(message)])
