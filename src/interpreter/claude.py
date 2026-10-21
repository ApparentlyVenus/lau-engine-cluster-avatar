import os

import anthropic

from interpreter.prompt import INTERPRETER_SYSTEM, interpreter_system
from llm_client import client, log_cache, touch

INTERPRETER_MODEL = os.environ.get("INTERPRETER_MODEL", "claude-haiku-4-5-20251001")
INTERPRETER_TIMEOUT_S = float(os.environ.get("INTERPRETER_TIMEOUT_S", "5"))

_use_stop = True


async def _create(message: str, system: list, use_stop: bool):
    extra = {"stop_sequences": ["}"]} if use_stop else {}
    touch()
    try:
        return await client.messages.create(
            model=INTERPRETER_MODEL,
            max_tokens=100,
            thinking={"type": "disabled"},
            system=system,
            messages=[{"role": "user", "content": message}],
            timeout=INTERPRETER_TIMEOUT_S,
            **extra,
        )
    finally:
        touch()


async def call_interpreter(message: str, persona=None) -> str:
    """persona: the patient, for the cached system blocks. Without one, only
    the rubric is sent (tools that classify lines out of context)."""
    global _use_stop
    system = interpreter_system(persona) if persona is not None else [
        {"type": "text", "text": INTERPRETER_SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]
    try:
        response = await _create(message, system, _use_stop)
    except anthropic.BadRequestError:
        if not _use_stop:
            raise
        _use_stop = False
        response = await _create(message, system, False)
    log_cache("interpreter", response.usage)

    for block in response.content:
        if block.type == "text":
            text = block.text
            if response.stop_reason == "stop_sequence" and response.stop_sequence:
                text += response.stop_sequence
            return text
    raise ValueError(f"No text block found in interpreter response: {response.content}")
