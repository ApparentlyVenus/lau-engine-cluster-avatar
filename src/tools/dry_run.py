import sys

from pipeline.interruption import should_interrupt
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state
from state_engine.turn_flags import TurnFlags


def print_state(label: str, state):
    print(f"\n--- {label} ---")
    print(f"trust={state.trust:.2f}  saturation={state.saturation:.2f}  unacknowledged={state.unacknowledged_turns}  turn={state.turn_count}")
    print(f"emotion: {state.emotion.primary.name} / {state.emotion.secondary.name} (blend={state.emotion.blend_weight:.2f}, intensity={state.emotion.intensity:.2f})")
    print(f"defense: {state.defense.mode.name} masking {state.defense.masking.name}")


def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)
    print(f"Loaded persona: {persona.scenario.patient_name}, age {persona.scenario.age}")

    state = build_initial_state(persona)
    print_state("Initial state", state)

    scripted_turns = [
        (
            "The doctor talked over her before she could ask a question.",
            TurnFlags(validating=0, silence_tolerance=0, premature_reassurance=0, jargon=0, logistics_first=0, interruption=0.9),
        ),
        (
            "Don't worry, we caught it early, it'll be fine.",
            TurnFlags(validating=0, silence_tolerance=0, premature_reassurance=0.8, jargon=0, logistics_first=0, interruption=0),
        ),
        (
            "So we'll need to schedule a biopsy follow-up and start staging next week.",
            TurnFlags(validating=0, silence_tolerance=0, premature_reassurance=0, jargon=0, logistics_first=0.9, interruption=0),
        ),
        (
            "That must be incredibly hard to hear.",
            TurnFlags(validating=0.9, silence_tolerance=0, premature_reassurance=0, jargon=0, logistics_first=0, interruption=0),
        ),
    ]

    for transcript, flags in scripted_turns:
        print(f'\nLearner: "{transcript}"')
        state, escalated = apply_turn(state, flags, persona) 
        print_state("After turn" + (" (ESCALATED)" if escalated else ""), state)

        interrupt_fired = should_interrupt(state, seconds_speaking=5.0, seconds_since_last_interruption=999.0, persona=persona)
        print(f"Would interrupt next learner turn? {interrupt_fired}")


if __name__ == "__main__":
    main(sys.argv[1])