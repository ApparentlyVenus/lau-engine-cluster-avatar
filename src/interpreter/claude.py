import os

import anthropic

from interpreter.prompt import INTERPRETER_TASK_PROMPT

client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

INTERPRETER_MODEL = os.environ.get("INTERPRETER_MODEL", "claude-haiku-4-5-20251001")


async def call_interpreter(message: str) -> str:
    response = await client.messages.create(
        model=INTERPRETER_MODEL,
        max_tokens=200,
        thinking={"type": "disabled"},
        system=[{"type": "text", "text": INTERPRETER_TASK_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": message}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    raise ValueError(f"No text block found in interpreter response: {response.content}")