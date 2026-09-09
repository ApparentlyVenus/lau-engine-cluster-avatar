import json

from patient_state import PatientState, EmotionState, DefenseState, EmotionMode, DefenseMode
from turn_flags import TurnFlags


def load_tuning(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def build_initial_state(tuning: dict) -> PatientState:
    init = tuning["initial_state"]
    emotion = EmotionState(
        primary=EmotionMode[init["emotion"]["primary"]],
        secondary=EmotionMode[init["emotion"]["secondary"]],
        blend_weight=init["emotion"]["blend_weight"],
        intensity=init["emotion"]["intensity"],
    )
    defense = DefenseState(
        mode=DefenseMode[init["defense"]["mode"]],
        masking=EmotionMode[init["defense"]["masking"]],
    )
    return PatientState(
        trust=init["trust"],
        saturation=init["saturation"],
        unacknowledged_turns=0,
        turn_count=0,
        emotion=emotion,
        defense=defense,
    )

def apply_turn(state: PatientState, flags: TurnFlags, tuning: dict) -> tuple[PatientState, bool]:
    deltas = tuning["flag_deltas"]
    personality = tuning["personality"]

    trust_delta = 0.0
    saturation_delta = 0.0
    turn_acknowledges = False

    for flag_name, intensity in flags.__dict__.items():
        if intensity <= 0:
            continue
        rule = deltas[flag_name]
        trust_delta += rule["trust"] * intensity
        saturation_delta += rule["saturation"] * intensity
        if rule["acknowledges"] and intensity >= personality["acknowledgment_intensity_threshold"]:
            turn_acknowledges = True

    new_trust = _clamp(state.trust + trust_delta)
    new_saturation = _clamp(state.saturation + saturation_delta)
    new_unacknowledged = 0 if turn_acknowledges else state.unacknowledged_turns + 1

    escalated = False
    if new_unacknowledged >= personality["unacknowledged_threshold"]:
        new_trust = _clamp(new_trust + personality["trust_penalty"])
        new_saturation = _clamp(new_saturation + personality["saturation_penalty"])
        new_unacknowledged = 0
        escalated = True

    new_turn_count = state.turn_count + 1
    new_emotion = _update_emotion(new_trust, new_saturation, new_turn_count)
    new_defense = _update_defense(new_trust, new_saturation, new_emotion, personality)

    new_state = PatientState(
        trust=new_trust,
        saturation=new_saturation,
        unacknowledged_turns=new_unacknowledged,
        turn_count=new_turn_count,
        emotion=new_emotion,
        defense=new_defense,
    )
    return new_state, escalated


def _update_emotion(trust: float, saturation: float, turn_count: int) -> EmotionState:
    shock = _clamp(0.65 - turn_count * 0.09)
    anger = _clamp(saturation * (1 - trust) * 1.3)
    grief = _clamp((1 - trust) * (1 - saturation) * 0.8 + (1 - trust) * 0.2)
    fear = _clamp((1 - trust) * 0.5 * (1 - shock))
    defensive = _clamp((1 - trust) * 0.4 + (0.25 if saturation > 0.65 else 0))

    raw = {
        EmotionMode.SHOCK: shock,
        EmotionMode.ANGER: anger,
        EmotionMode.GRIEF: grief,
        EmotionMode.FEAR: fear,
        EmotionMode.BARGAINING: defensive,
    }

    ranked = sorted(raw.items(), key=lambda item: item[1], reverse=True)
    primary, primary_value = ranked[0]
    secondary, secondary_value = ranked[1]

    total = primary_value + secondary_value
    blend_weight = secondary_value / total if total > 0 else 0.0
    intensity = _clamp(primary_value)

    return EmotionState(
        primary=primary,
        secondary=secondary,
        blend_weight=blend_weight,
        intensity=intensity,
    )


def _update_defense(trust: float, saturation: float, emotion: EmotionState, personality: dict) -> DefenseState:
    threshold = personality["defense_trigger_trust"]
    if trust >= threshold:
        return DefenseState(mode=DefenseMode.NONE, masking=EmotionMode.NONE)

    mode = DefenseMode[personality["preferred_defense_mode"]]
    return DefenseState(mode=mode, masking=emotion.primary)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))