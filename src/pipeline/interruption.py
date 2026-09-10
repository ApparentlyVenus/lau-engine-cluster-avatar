import random

from state_engine.patient_state import EmotionMode

INTERRUPT_LINE_BANK = {
    "anger_interrupt": [
        "No, wait.",
        "You're not even listening to me.",
    ],
    "panic_interrupt": [
        "Wait, what- what did you just say?",
        "Hold on, I don't- slow down.",
    ],
}

_last_used_line = {}


def select_interrupt_category(state):
    if state.emotion.primary == EmotionMode.ANGER:
        return "anger_interrupt"
    if state.emotion.primary == EmotionMode.FEAR:
        return "panic_interrupt"
    return None


def pick_line(category: str) -> str:
    lines = INTERRUPT_LINE_BANK[category]
    last = _last_used_line.get(category)
    choices = [line for line in lines if line != last] or lines
    chosen = random.choice(choices)
    _last_used_line[category] = chosen
    return chosen


def should_interrupt(state, seconds_speaking: float, seconds_since_last_interruption: float, persona) -> bool:
    cfg = persona.interruption

    if state.emotion.primary not in cfg.trigger_emotions:
        return False
    if state.emotion.intensity < cfg.min_intensity:
        return False
    if seconds_speaking < cfg.min_seconds_before_interrupt:
        return False
    if seconds_since_last_interruption < cfg.cooldown_seconds:
        return False

    probability = cfg.base_probability * state.emotion.intensity
    return random.random() < probability