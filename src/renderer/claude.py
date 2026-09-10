import os
import anthropic

from renderer.prompt import RENDERER_TASK_PROMPT

client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

RENDERER_MODEL = os.environ.get("RENDERER_MODEL", "claude-sonnet-5")


async def call_renderer(message: str) -> str:
    response = await client.messages.create(
        model=RENDERER_MODEL,
        max_tokens=150,
        system=RENDERER_TASK_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text