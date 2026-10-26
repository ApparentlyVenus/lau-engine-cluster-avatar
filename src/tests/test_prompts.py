from interpreter.prompt import build_interpreter_message
from renderer.prompt import build_renderer_message
from state_engine.engine import apply_turn, build_initial_state
from state_engine.turn_flags import TurnFlags


def zero_flags(**overrides):
    base = {"validating": 0, "silence_tolerance": 0, "premature_reassurance": 0, "jargon": 0, "logistics_first": 0, "interruption": 0}
    base.update(overrides)
    return TurnFlags(**base)


def test_interpreter_message_includes_transcript(persona):
    message = build_interpreter_message(persona, "I don't know what to say.", [])
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


# --- prompt caching layout ----------------------------------------------------

from interpreter.prompt import INTERPRETER_SYSTEM, interpreter_system  # noqa: E402
from renderer.prompt import RENDERER_SYSTEM, renderer_system  # noqa: E402

# Haiku 4.5 caches only >= 4,096 tokens. English runs about 3.5-4 characters a
# token, so these keep a margin; src/tools/prompt_tokens.py gives exact counts.
MIN_STATIC_CHARS = 16000


def test_static_prompts_long_enough_to_cache():
    assert len(INTERPRETER_SYSTEM) >= MIN_STATIC_CHARS
    assert len(RENDERER_SYSTEM) >= MIN_STATIC_CHARS


def test_system_blocks_layout(persona, persona_dict):
    from state_engine.config import PersonaConfig

    other = dict(persona_dict, scenario={"patient_name": "Rami Khoury", "age": 61, "prompt": "Another scenario."})
    other = PersonaConfig._from_dict(other)
    for build in (interpreter_system, renderer_system):
        a, b = build(persona), build(other)
        assert len(a) == 2 and all(blk["cache_control"] == {"type": "ephemeral"} for blk in a)
        assert a[0] == b[0]                      # shared rubric: one cache entry for every patient
        assert persona.scenario.patient_name in a[1]["text"] and "Rami Khoury" in b[1]["text"]
        assert a == build(persona)               # deterministic, so later calls read the cache


def test_static_prompts_name_no_patient(persona):
    for text in (INTERPRETER_SYSTEM, RENDERER_SYSTEM):
        assert "Haddad" not in text and "Layla" not in text


def test_per_turn_messages_leave_scenario_to_system(persona):
    state = build_initial_state(persona)
    assert persona.scenario.prompt not in build_interpreter_message(persona, "Hello.", [])
    assert persona.scenario.prompt not in build_renderer_message(persona, state, "Hello.")



def test_parser_reads_disclosure_and_answers():
    from interpreter.parser import parse_turn_flags

    f = parse_turn_flags('{"discloses_news": 1.0, "logistics_first": 0.8, "answers_question": 1.0}')
    assert f.discloses_news == 1.0 and f.answers_question == 1.0 and f.logistics_first == 0.0


def test_renderer_message_news_style_and_ending(persona):
    from dataclasses import replace

    state = build_initial_state(persona)
    before = build_renderer_message(persona, state, "Hello.")
    assert "has not been told" in before and "How she speaks right now:" in before
    told, _ = apply_turn(state, TurnFlags(discloses_news=1.0), persona)
    after = build_renderer_message(persona, told, "It is cancer.")
    assert "has been told" in after and "Halting" in after  # shock's speech style
    assert "ending the consultation" in build_renderer_message(persona, replace(told, ended=True), "x")


def test_clinical_facts_reach_the_scorer_not_her(persona):
    from dataclasses import replace

    from interpreter.prompt import interpreter_persona_block
    from renderer.prompt import renderer_persona_block

    persona.scenario = replace(persona.scenario, clinical_facts="Invasive ductal carcinoma, stage IIB.")
    assert "stage IIB" in interpreter_persona_block(persona)
    assert "stage IIB" not in renderer_persona_block(persona)
