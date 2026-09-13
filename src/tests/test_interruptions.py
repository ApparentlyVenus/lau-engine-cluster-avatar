from unittest.mock import patch

from pipeline.interruption import (
    INTERRUPT_LINE_BANK,
    pick_line,
    select_interrupt_category,
    should_interrupt,
)
from state_engine.patient_state import (
    DefenseMode,
    DefenseState,
    EmotionMode,
    EmotionState,
    PatientState,
)


def make_state(primary, intensity):
    return PatientState(
        trust=0.3,
        saturation=0.7,
        unacknowledged_turns=0,
        turn_count=1,
        emotion=EmotionState(primary=primary, secondary=EmotionMode.NONE, blend_weight=0.0, intensity=intensity),
        defense=DefenseState(mode=DefenseMode.NONE, masking=EmotionMode.NONE),
    )


def test_does_not_interrupt_when_emotion_not_a_trigger(persona):
    state = make_state(EmotionMode.GRIEF, intensity=0.9)
    assert should_interrupt(state, seconds_speaking=10, seconds_since_last_interruption=999, persona=persona) is False


def test_does_not_interrupt_below_min_intensity(persona):
    state = make_state(EmotionMode.ANGER, intensity=0.4)
    assert should_interrupt(state, seconds_speaking=10, seconds_since_last_interruption=999, persona=persona) is False


def test_does_not_interrupt_before_min_seconds(persona):
    state = make_state(EmotionMode.ANGER, intensity=0.9)
    assert should_interrupt(state, seconds_speaking=1.0, seconds_since_last_interruption=999, persona=persona) is False


def test_does_not_interrupt_during_cooldown(persona):
    state = make_state(EmotionMode.ANGER, intensity=0.9)
    assert should_interrupt(state, seconds_speaking=10, seconds_since_last_interruption=1.0, persona=persona) is False


def test_interrupts_when_all_conditions_met_and_roll_succeeds(persona):
    state = make_state(EmotionMode.ANGER, intensity=0.9)
    with patch("random.random", return_value=0.0):
        assert should_interrupt(state, seconds_speaking=10, seconds_since_last_interruption=999, persona=persona) is True


def test_does_not_interrupt_when_roll_fails(persona):
    state = make_state(EmotionMode.ANGER, intensity=0.9)
    with patch("random.random", return_value=0.999):
        assert should_interrupt(state, seconds_speaking=10, seconds_since_last_interruption=999, persona=persona) is False


def test_select_interrupt_category_maps_correctly():
    assert select_interrupt_category(make_state(EmotionMode.ANGER, 0.9)) == "anger_interrupt"
    assert select_interrupt_category(make_state(EmotionMode.FEAR, 0.9)) == "panic_interrupt"
    assert select_interrupt_category(make_state(EmotionMode.GRIEF, 0.9)) is None


def test_pick_line_stays_within_bank():
    for _ in range(20):
        line = pick_line("anger_interrupt")
        assert line in INTERRUPT_LINE_BANK["anger_interrupt"]


def test_pick_line_avoids_immediate_repeat():
    seen = [pick_line("anger_interrupt") for _ in range(20)]
    consecutive_repeats = sum(1 for a, b in zip(seen, seen[1:]) if a == b)
    assert consecutive_repeats == 0