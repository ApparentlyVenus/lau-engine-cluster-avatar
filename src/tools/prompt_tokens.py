"""Are the system prompts long enough to be cached?

    python src/tools/prompt_tokens.py                    # default patient
    python src/tools/prompt_tokens.py path/to/tuning.json

Claude Haiku 4.5 only caches a prompt prefix of at least 4,096 tokens; below
that, cache_control is silently ignored. This counts the real tokens (free
API call) for each cache breakpoint: the shared rubric alone, and rubric plus
this patient's block.
"""

import asyncio
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from interpreter.claude import INTERPRETER_MODEL  # noqa: E402
from interpreter.prompt import interpreter_system  # noqa: E402
from llm_client import client  # noqa: E402
from renderer.claude import RENDERER_MODEL  # noqa: E402
from renderer.prompt import renderer_system  # noqa: E402
from state_engine.config import PersonaConfig  # noqa: E402

MINIMUM = 4096
# count_tokens needs a message; this one's tokens are subtracted out.
PROBE = [{"role": "user", "content": "x"}]


async def count(model: str, system: list) -> int:
    with_system = await client.messages.count_tokens(model=model, system=system, messages=PROBE)
    bare = await client.messages.count_tokens(model=model, messages=PROBE)
    return with_system.input_tokens - bare.input_tokens


async def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(SRC / "state_engine" / "tuning" / "tuning.json")
    persona = PersonaConfig.from_file(path)
    for name, model, system in (
        ("interpreter", INTERPRETER_MODEL, interpreter_system(persona)),
        ("renderer", RENDERER_MODEL, renderer_system(persona)),
    ):
        shared = await count(model, system[:1])
        full = await count(model, system)
        for label, n in (("shared rubric", shared), ("+ patient block", full)):
            ok = n >= MINIMUM
            print(f"{'OK  ' if ok else 'FAIL'}  {name:<12} {label:<16} {n:>5} tokens"
                  + ("" if ok else f"  (needs {MINIMUM}; not cached)"))


if __name__ == "__main__":
    asyncio.run(main())
