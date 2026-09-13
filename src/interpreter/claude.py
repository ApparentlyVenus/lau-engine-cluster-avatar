import os

import anthropic

from interpreter.prompt import INTERPRETER_TASK_PROMPT

client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

INTERPRETER_MODEL = os.environ.get("INTERPRETER_MODEL", "claude-haiku-4-5-20251001")

async def call_interpreter(message: str) -> str:
    response = await client.messages.create(
        model=INTERPRETER_MODEL,
        max_tokens=200,
        system=INTERPRETER_TASK_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text