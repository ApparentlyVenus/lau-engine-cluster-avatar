from interpreter.prompt import build_interpreter_message
from renderer.prompt import build_renderer_message
from state_engine.engine import apply_turn, build_initial_state
from state_engine.turn_flags import TurnFlags


def zero_flags(**overrides):
    base = dict(validating=0, silence_tolerance=0, premature_reassurance=0, jargon=0, logistics_first=0, interruption=0)
    base.update(overrides)
    return TurnFlags(**base)


def test_interpreter_message_includes_scenario_and_transcript(persona):
    message = build_interpreter_message(persona, "I don't know what to say.", [])
    assert persona.scenario.patient_name in message
    assert "I don't know what to say." in message
    assert "no prior turns" in message


def test_interpreter_message_includes_history(persona):
    message = build_interpreter_message(persona, "Okay.", ["First line", "Second line"])
    assert "First line" in message
    assert "Second line" in message


def test_renderer_message_includes_allowed_tags_for_current_emotion(persona):
    state = build_initial_state(persona)
    message = build_renderer_message(persona, state, "Hello.")
    for tag in persona.allowed_tags(state.emotion.primary):
        assert tag in message


def test_renderer_message_includes_defense_line_when_active(persona):
    state = build_initial_state(persona)
    for _ in range(10):
        state, _ = apply_turn(state, zero_flags(interruption=1.0), persona)
    message = build_renderer_message(persona, state, "Whatever.")
    assert "masking" in message


def test_renderer_message_omits_defense_line_when_inactive(persona):
    state = build_initial_state(persona)
    message = build_renderer_message(persona, state, "Whatever.")
    assert "masking" not in message


def test_renderer_message_includes_filler_note_when_given(persona):
    state = build_initial_state(persona)
    message = build_renderer_message(persona, state, "Whatever.", filler_line="No, wait.")
    assert "No, wait." in message
    assert "already interrupted" in message