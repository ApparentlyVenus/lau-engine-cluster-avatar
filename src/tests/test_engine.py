from state_engine.engine import apply_turn, build_initial_state
from state_engine.patient_state import DefenseMode, EmotionMode
from state_engine.turn_flags import TurnFlags


def zero_flags(**overrides):
    base = {"validating": 0, "silence_tolerance": 0, "premature_reassurance": 0, "jargon": 0, "logistics_first": 0, "interruption": 0}
    base.update(overrides)
    return TurnFlags(**base)


def test_initial_state_matches_persona(persona):
    state = build_initial_state(persona)
    assert state.trust == 0.50
    assert state.saturation == 0.40
    assert state.unacknowledged_turns == 0
    assert state.turn_count == 0
    assert state.emotion.primary == EmotionMode.SHOCK
    assert state.defense.mode == DefenseMode.NONE


def test_validating_increases_trust_and_lowers_saturation(persona):
    state = build_initial_state(persona)
    new_state, escalated = apply_turn(state, zero_flags(validating=1.0), persona)
    assert new_state.trust > state.trust
    assert new_state.saturation < state.saturation
    assert escalated is False


def test_validating_resets_unacknowledged_counter(persona):
    state = build_initial_state(persona)
    state, _ = apply_turn(state, zero_flags(jargon=1.0), persona)
    state, _ = apply_turn(state, zero_flags(jargon=1.0), persona)
    assert state.unacknowledged_turns == 2
    state, _ = apply_turn(state, zero_flags(validating=1.0), persona)
    assert state.unacknowledged_turns == 0


def test_weak_validation_below_threshold_does_not_acknowledge(persona):
    state = build_initial_state(persona)
    state, _ = apply_turn(state, zero_flags(jargon=1.0), persona)
    state, _ = apply_turn(state, zero_flags(validating=0.1), persona)
    assert state.unacknowledged_turns == 2


def test_escalation_triggers_at_threshold(persona):
    state = build_initial_state(persona)
    escalated_flags = []
    for _ in range(persona.personality.unacknowledged_threshold):
        state, escalated = apply_turn(state, zero_flags(jargon=1.0), persona)
        escalated_flags.append(escalated)
    assert escalated_flags[-1] is True
    assert all(e is False for e in escalated_flags[:-1])
    assert state.unacknowledged_turns == 0


def test_trust_never_exceeds_bounds(persona):
    state = build_initial_state(persona)
    for _ in range(50):
        state, _ = apply_turn(state, zero_flags(validating=1.0, silence_tolerance=1.0), persona)
    assert 0.0 <= state.trust <= 1.0
    assert 0.0 <= state.saturation <= 1.0


def test_saturation_never_goes_negative(persona):
    state = build_initial_state(persona)
    for _ in range(50):
        state, _ = apply_turn(state, zero_flags(validating=1.0), persona)
    assert state.saturation >= 0.0


def test_defense_activates_below_trigger_trust(persona):
    state = build_initial_state(persona)
    for _ in range(10):
        state, _ = apply_turn(state, zero_flags(interruption=1.0), persona)
    assert state.trust < persona.personality.defense_trigger_trust
    assert state.defense.mode == persona.personality.preferred_defense_mode
    assert state.defense.masking == state.emotion.primary


def test_defense_clears_above_trigger_trust(persona):
    state = build_initial_state(persona)
    for _ in range(10):
        state, _ = apply_turn(state, zero_flags(interruption=1.0), persona)
    assert state.defense.mode != DefenseMode.NONE

    for _ in range(10):
        state, _ = apply_turn(state, zero_flags(validating=1.0, silence_tolerance=1.0), persona)
    assert state.defense.mode == DefenseMode.NONE


def test_emotion_primary_and_secondary_are_never_the_same(persona):
    state = build_initial_state(persona)
    for _ in range(20):
        state, _ = apply_turn(state, zero_flags(jargon=1.0, logistics_first=0.5), persona)
        assert state.emotion.primary != state.emotion.secondary


def test_multiple_flags_in_one_turn_combine(persona):
    state = build_initial_state(persona)
    only_jargon, _ = apply_turn(state, zero_flags(jargon=1.0), persona)
    both, _ = apply_turn(state, zero_flags(jargon=1.0, logistics_first=1.0), persona)
    assert both.trust < only_jargon.trust