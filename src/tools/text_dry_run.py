import sys
import time

from dotenv import load_dotenv  # type: ignore

load_dotenv()

import asyncio

from interpreter.claude import call_interpreter
from interpreter.parser import parse_turn_flags
from interpreter.prompt import build_interpreter_message
from renderer.claude import call_renderer
from renderer.prompt import build_renderer_message
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state


def print_state(state):
    print(f"trust={state.trust:.2f}  saturation={state.saturation:.2f}  unacknowledged={state.unacknowledged_turns}")
    print(f"emotion: {state.emotion.primary.name} / {state.emotion.secondary.name} (blend={state.emotion.blend_weight:.2f}, intensity={state.emotion.intensity:.2f})")
    print(f"defense: {state.defense.mode.name} masking {state.defense.masking.name}")


async def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)
    state = build_initial_state(persona)
    interpreter_history: list[str] = []
    conversation: list[str] = []

    print(f"Loaded persona: {persona.scenario.patient_name}, age {persona.scenario.age}")
    print_state(state)
    print("\nType the learner's line, or 'quit' to stop.\n")

    while True:
        transcript = input("Learner: ").strip()
        if transcript.lower() == "quit":
            break

        t0 = time.monotonic()
        message = build_interpreter_message(persona, transcript, interpreter_history)
        raw_response = await call_interpreter(message)
        flags = parse_turn_flags(raw_response)
        t1 = time.monotonic()
        print(f"[flags] {flags}  ({(t1 - t0) * 1000:.0f}ms)")

        state, escalated = apply_turn(state, flags, persona)
        interpreter_history.append(transcript)
        conversation.append(f"Learner: {transcript}")

        t2 = time.monotonic()
        print_state(state)
        print(f"[state engine] ({(t2 - t1) * 1000:.1f}ms)")
        if escalated:
            print("*** ESCALATED ***")

        renderer_message = build_renderer_message(persona, state, transcript, history=conversation)
        line = await call_renderer(renderer_message)
        t3 = time.monotonic()
        conversation.append(f"Patient: {line}")

        print(f"\nPatient: {line}   ({(t3 - t2) * 1000:.0f}ms)")
        print(f"[turn total: {(t3 - t0) * 1000:.0f}ms]\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))