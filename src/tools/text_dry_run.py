"""Typed learner lines through real Claude, with timings.

    python tools/text_dry_run.py tuning.json            # speculative renderer
    python tools/text_dry_run.py tuning.json --serial   # old serial path, for comparison
"""

import sys
import time

from dotenv import load_dotenv  # type: ignore

load_dotenv()

import asyncio

from interpreter.claude import call_interpreter
from interpreter.parser import parse_turn_flags
from interpreter.prompt import build_interpreter_message
from renderer.claude import stream_renderer
from renderer.prompt import build_renderer_message
from renderer.speculation import speculative_render
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state
from state_engine.turn_flags import TurnFlags


def print_state(state):
    print(f"trust={state.trust:.2f}  saturation={state.saturation:.2f}  unacknowledged={state.unacknowledged_turns}")
    print(f"emotion: {state.emotion.primary.name} / {state.emotion.secondary.name} (blend={state.emotion.blend_weight:.2f}, intensity={state.emotion.intensity:.2f})")
    print(f"defense: {state.defense.mode.name} masking {state.defense.masking.name}")


async def main(persona_path: str, serial: bool):
    persona = PersonaConfig.from_file(persona_path)
    state = build_initial_state(persona)
    # One shared history, both sides, like the live pipeline. This tool used to
    # give the interpreter learner-only lines, which the pipeline stopped doing.
    conversation: list[str] = []
    hits = misses = 0

    print(f"Loaded persona: {persona.scenario.patient_name}, age {persona.scenario.age}")
    print(f"Mode: {'serial' if serial else 'speculative'}")
    print_state(state)
    print("\nType the learner's line, or 'quit' to stop.\n")

    while True:
        transcript = (await asyncio.to_thread(input, "Learner: ")).strip()
        if transcript.lower() == "quit":
            break
        if not transcript:
            continue

        t0 = time.monotonic()
        interp_message = build_interpreter_message(persona, transcript, conversation)
        conversation.append(f"Learner: {transcript}")
        snapshot = list(conversation)
        timings: dict[str, float] = {}
        result: dict = {}

        async def interpret():
            raw = await call_interpreter(interp_message)  # noqa: B023
            flags = parse_turn_flags(raw)
            timings["interp"] = time.monotonic() - t0 # noqa: B023
            new_state, escalated = apply_turn(state, flags, persona) # noqa: B023
            result.update(flags=flags, state=new_state, escalated=escalated) # noqa: B023
            return build_renderer_message(persona, new_state, transcript, history=snapshot) # noqa: B023

        chunks: list[str] = []

        async def emit(chunk):
            timings.setdefault("first_chunk", time.monotonic() - t0)  # noqa: B023
            chunks.append(chunk)  # noqa: B023

        if serial:
            real_message = await interpret()
            async for chunk in stream_renderer(real_message):
                await emit(chunk)
            hit = None
        else:
            predicted, _ = apply_turn(state, TurnFlags(), persona)
            spec_message = build_renderer_message(persona, predicted, transcript, history=snapshot)
            _, hit = await speculative_render(spec_message, interpret(), stream_renderer, emit)
            hits += hit
            misses += not hit

        total = time.monotonic() - t0
        state = result["state"]
        line = " ".join(chunks)
        conversation.append(f"Patient: {line}")

        print(f"[flags] {result['flags']}")
        print_state(state)
        if result["escalated"]:
            print("*** ESCALATED ***")
        print(f"\nPatient: {line}")
        spec = "" if hit is None else f"  speculation {'HIT' if hit else 'MISS'} ({hits}/{hits + misses})"
        print(
            f"[interpreter {timings['interp'] * 1000:.0f}ms | first chunk {timings.get('first_chunk', total) * 1000:.0f}ms"
            f" | full line {total * 1000:.0f}ms]{spec}\n"
        )


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(main(args[0], "--serial" in args))
