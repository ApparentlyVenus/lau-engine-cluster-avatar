import pytest

from state_engine.engine import apply_turn, build_initial_state
from state_engine.patient_state import DefenseMode, EmotionMode
from state_engine.turn_flags import TurnFlags


def zero_flags(**overrides):
    base = {"validating": 0, "silence_tolerance": 0, "premature_reassurance": 0, "jargon": 0, "logistics_first": 0, "interruption": 0}
    base.update(overrides)
    return TurnFlags(**base)


def told(state, persona):
    """Deliver the news, so the post-disclosure rules apply. The counter is
    reset so tests count from zero."""
    from dataclasses import replace

    state, _ = apply_turn(state, TurnFlags(discloses_news=1.0), persona)
    return replace(state, unacknowledged_turns=0)


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
    state = told(build_initial_state(persona), persona)
    state, _ = apply_turn(state, zero_flags(jargon=1.0), persona)
    state, _ = apply_turn(state, zero_flags(jargon=1.0), persona)
    assert state.unacknowledged_turns == 2
    state, _ = apply_turn(state, zero_flags(validating=1.0), persona)
    assert state.unacknowledged_turns == 0


def test_weak_validation_below_threshold_does_not_acknowledge(persona):
    state = told(build_initial_state(persona), persona)
    state, _ = apply_turn(state, zero_flags(jargon=1.0), persona)
    state, _ = apply_turn(state, zero_flags(validating=0.1), persona)
    assert state.unacknowledged_turns == 2


def test_escalation_triggers_at_threshold(persona):
    state = told(build_initial_state(persona), persona)
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
    for _ in range(4):
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


# --- emotional arc ----------------------------------------------------------------

def test_no_shock_before_the_news(persona):
    state = build_initial_state(persona)
    for _ in range(3):
        state, _ = apply_turn(state, TurnFlags(), persona)
    assert not state.news_delivered and state.shock == 0
    assert state.emotion.primary in (EmotionMode.CALM, EmotionMode.FEAR)
    assert state.unacknowledged_turns == 0  # small talk is not ignoring her


def test_disclosure_starts_shock_and_adds_saturation(persona):
    state = build_initial_state(persona)
    after, _ = apply_turn(state, TurnFlags(discloses_news=1.0), persona)
    assert after.news_delivered and after.shock == persona.arc.shock_peak
    assert after.emotion.primary == EmotionMode.SHOCK
    assert after.saturation == pytest.approx(state.saturation + persona.arc.disclosure_saturation)
    again, _ = apply_turn(after, TurnFlags(discloses_news=1.0), persona)
    assert again.shock < after.shock  # only the first disclosure counts


def test_space_fades_shock_faster_than_rushing(persona):
    state = told(build_initial_state(persona), persona)
    gentle, _ = apply_turn(state, TurnFlags(validating=0.8, silence_tolerance=0.8), persona)
    rushed, _ = apply_turn(state, TurnFlags(logistics_first=0.9), persona)
    assert gentle.shock < rushed.shock


def test_good_path_reaches_grief_or_calm_poor_path_anger(persona):
    good = told(build_initial_state(persona), persona)
    for _ in range(6):
        good, _ = apply_turn(good, TurnFlags(validating=0.7, silence_tolerance=0.5), persona)
    assert good.emotion.primary in (EmotionMode.GRIEF, EmotionMode.CALM)

    poor = told(build_initial_state(persona), persona)
    for _ in range(4):
        poor, _ = apply_turn(poor, TurnFlags(logistics_first=0.8, jargon=0.5), persona)
    assert poor.emotion.primary == EmotionMode.ANGER


def test_jargon_lowers_competence_and_answers_raise_it(persona):
    state = build_initial_state(persona)
    worse, _ = apply_turn(state, TurnFlags(jargon=1.0), persona)
    better, _ = apply_turn(state, TurnFlags(answers_question=1.0), persona)
    assert worse.competence < state.competence < better.competence


def test_she_walks_out_after_sustained_low_trust(persona):
    state = build_initial_state(persona)
    for _ in range(10):
        state, _ = apply_turn(state, TurnFlags(disrespect=1.0), persona)
        if state.ended:
            break
    assert state.ended
    frozen, _ = apply_turn(state, TurnFlags(validating=1.0), persona)
    assert frozen is state  # nothing changes once she has left
