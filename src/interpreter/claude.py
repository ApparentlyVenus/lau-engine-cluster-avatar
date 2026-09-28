import os

import anthropic

from interpreter.prompt import INTERPRETER_TASK_PROMPT
from llm_client import client, touch

INTERPRETER_MODEL = os.environ.get("INTERPRETER_MODEL", "claude-haiku-4-5-20251001")
INTERPRETER_TIMEOUT_S = float(os.environ.get("INTERPRETER_TIMEOUT_S", "5"))

_use_stop = True


async def _create(message: str, use_stop: bool):
    extra = {"stop_sequences": ["}"]} if use_stop else {}
    touch()
    try:
        return await client.messages.create(
            model=INTERPRETER_MODEL,
            max_tokens=100,
            thinking={"type": "disabled"},
            system=[{"type": "text", "text": INTERPRETER_TASK_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": message}],
            timeout=INTERPRETER_TIMEOUT_S,
            **extra,
        )
    finally:
        touch()


async def call_interpreter(message: str) -> str:
    global _use_stop
    try:
        response = await _create(message, _use_stop)
    except anthropic.BadRequestError:
        if not _use_stop:
            raise
        _use_stop = False
        response = await _create(message, False)

    for block in response.content:
        if block.type == "text":
            text = block.text
            if response.stop_reason == "stop_sequence" and response.stop_sequence:
                text += response.stop_sequence
            return text
    raise ValueError(f"No text block found in interpreter response: {response.content}")
