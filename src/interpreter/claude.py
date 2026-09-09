import os
import anthropic

from interpreter.prompt import SYSTEM_PROMPT, build_user_message

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

INTERPRETER_MODEL = os.environ.get("INTERPRETER_MODEL", "claude-haiku-4-5-20251001")


def call_interpreter(transcript: str, history: list[str]) -> str:
    message = client.messages.create(
        model=INTERPRETER_MODEL,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_user_message(transcript, history)}
        ],
    )
    return message.content[0].text