import json
import sys

REQUIRED_FLAGS = [
    "validating",
    "silence_tolerance",
    "premature_reassurance",
    "jargon",
    "logistics_first",
    "interruption",
]

VALID_EMOTIONS = {"NONE", "SHOCK", "ANGER", "GRIEF", "FEAR", "BARGAINING"}
VALID_DEFENSE_MODES = {"NONE", "SARCASM", "INTELLECTUALIZING", "MINIMIZING"}


class TuningValidationError(Exception):
    pass


def validate_tuning_file(path: str) -> None:
    with open(path, "r") as f:
        tuning = json.load(f)

    errors = []
    errors += _validate_scenario(tuning)
    errors += _validate_severity_scale(tuning)
    errors += _validate_audio_tags(tuning)
    errors += _validate_personality(tuning)
    errors += _validate_interruption(tuning)
    errors += _validate_initial_state(tuning)
    errors += _validate_flag_deltas(tuning)

    if errors:
        raise TuningValidationError("\n".join(errors))


def _validate_scenario(tuning: dict) -> list[str]:
    if "scenario" not in tuning:
        return ["Missing top-level key: scenario"]
    scenario = tuning["scenario"]
    errors = []
    for key in ("patient_name", "age", "prompt"):
        if key not in scenario:
            errors.append(f"Missing scenario.{key}")
    if "age" in scenario and not isinstance(scenario["age"], int):
        errors.append("scenario.age must be an integer")
    return errors


def _validate_severity_scale(tuning: dict) -> list[str]:
    errors = []
    if "severity_scale" not in tuning:
        return ["Missing top-level key: severity_scale"]

    scale = tuning["severity_scale"]
    for band_group in ("trust_bands", "saturation_bands"):
        if band_group not in scale:
            errors.append(f"Missing severity_scale.{band_group}")
            continue
        for band_name, band in scale[band_group].items():
            for key in ("min", "max", "description"):
                if key not in band:
                    errors.append(f"severity_scale.{band_group}.{band_name} missing {key}")
            if "min" in band and "max" in band:
                if band["min"] > band["max"]:
                    errors.append(f"severity_scale.{band_group}.{band_name} has min > max")
                if not (0.0 <= band["min"] <= 1.0) or not (0.0 <= band["max"] <= 1.0):
                    errors.append(f"severity_scale.{band_group}.{band_name} out of 0-1 range")
    return errors


def _validate_audio_tags(tuning: dict) -> list[str]:
    if "audio_tags" not in tuning:
        return ["Missing top-level key: audio_tags"]
    errors = []
    tags = tuning["audio_tags"]
    for emotion_name, tag_list in tags.items():
        if emotion_name not in VALID_EMOTIONS or emotion_name == "NONE":
            errors.append(f"audio_tags has invalid emotion key: {emotion_name}")
        if not isinstance(tag_list, list) or not all(isinstance(t, str) for t in tag_list):
            errors.append(f"audio_tags.{emotion_name} must be a list of strings")
    return errors


def _validate_personality(tuning: dict) -> list[str]:
    errors = []
    if "personality" not in tuning:
        return ["Missing top-level key: personality"]

    personality = tuning["personality"]
    required_keys = [
        "preferred_defense_mode",
        "acknowledgment_intensity_threshold",
        "unacknowledged_threshold",
        "trust_penalty",
        "saturation_penalty",
        "defense_trigger_trust",
    ]
    for key in required_keys:
        if key not in personality:
            errors.append(f"Missing personality.{key}")

    if "preferred_defense_mode" in personality:
        mode = personality["preferred_defense_mode"]
        if mode not in VALID_DEFENSE_MODES or mode == "NONE":
            errors.append(f"personality.preferred_defense_mode invalid: {mode}")

    if "unacknowledged_threshold" in personality:
        value = personality["unacknowledged_threshold"]
        if not isinstance(value, int) or value < 1:
            errors.append("personality.unacknowledged_threshold must be a positive integer")

    for key in ("acknowledgment_intensity_threshold", "defense_trigger_trust"):
        if key in personality and not (0.0 <= personality[key] <= 1.0):
            errors.append(f"personality.{key} must be between 0 and 1")

    return errors


def _validate_interruption(tuning: dict) -> list[str]:
    if "interruption" not in tuning:
        return ["Missing top-level key: interruption"]
    errors = []
    cfg = tuning["interruption"]

    if "trigger_emotions" not in cfg:
        errors.append("Missing interruption.trigger_emotions")
    else:
        for emotion_name in cfg["trigger_emotions"]:
            if emotion_name not in VALID_EMOTIONS or emotion_name == "NONE":
                errors.append(f"interruption.trigger_emotions has invalid emotion: {emotion_name}")

    for key in ("min_intensity", "base_probability"):
        if key not in cfg:
            errors.append(f"Missing interruption.{key}")
        elif not (0.0 <= cfg[key] <= 1.0):
            errors.append(f"interruption.{key} must be between 0 and 1")

    for key in ("min_seconds_before_interrupt", "cooldown_seconds"):
        if key not in cfg:
            errors.append(f"Missing interruption.{key}")
        elif cfg[key] < 0:
            errors.append(f"interruption.{key} must be non-negative")

    return errors


def _validate_initial_state(tuning: dict) -> list[str]:
    errors = []
    if "initial_state" not in tuning:
        return ["Missing top-level key: initial_state"]

    init = tuning["initial_state"]

    for key in ("trust", "saturation"):
        if key not in init:
            errors.append(f"Missing initial_state.{key}")
        elif not (0.0 <= init[key] <= 1.0):
            errors.append(f"initial_state.{key} must be between 0 and 1")

    if "emotion" not in init:
        errors.append("Missing initial_state.emotion")
    else:
        emotion = init["emotion"]
        for key in ("primary", "secondary"):
            if key not in emotion:
                errors.append(f"Missing initial_state.emotion.{key}")
            elif emotion[key] not in VALID_EMOTIONS:
                errors.append(f"initial_state.emotion.{key} invalid: {emotion[key]}")
        for key in ("blend_weight", "intensity"):
            if key not in emotion:
                errors.append(f"Missing initial_state.emotion.{key}")
            elif not (0.0 <= emotion[key] <= 1.0):
                errors.append(f"initial_state.emotion.{key} must be between 0 and 1")

    if "defense" not in init:
        errors.append("Missing initial_state.defense")
    else:
        defense = init["defense"]
        for key in ("mode", "masking"):
            if key not in defense:
                errors.append(f"Missing initial_state.defense.{key}")
        if "mode" in defense and defense["mode"] not in VALID_DEFENSE_MODES:
            errors.append(f"initial_state.defense.mode invalid: {defense['mode']}")
        if "masking" in defense and defense["masking"] not in VALID_EMOTIONS:
            errors.append(f"initial_state.defense.masking invalid: {defense['masking']}")

    if "unacknowledged_turns" in init or "turn_count" in init:
        errors.append("initial_state should not contain unacknowledged_turns or turn_count (always zero, removed from schema)")

    return errors


def _validate_flag_deltas(tuning: dict) -> list[str]:
    errors = []
    if "flag_deltas" not in tuning:
        return ["Missing top-level key: flag_deltas"]

    deltas = tuning["flag_deltas"]
    for flag_name in REQUIRED_FLAGS:
        if flag_name not in deltas:
            errors.append(f"Missing flag_deltas.{flag_name}")
            continue
        rule = deltas[flag_name]
        for key in ("trust", "saturation", "acknowledges"):
            if key not in rule:
                errors.append(f"flag_deltas.{flag_name} missing {key}")
        if "acknowledges" in rule and not isinstance(rule["acknowledges"], bool):
            errors.append(f"flag_deltas.{flag_name}.acknowledges must be true/false")

    unexpected = set(deltas.keys()) - set(REQUIRED_FLAGS)
    if unexpected:
        errors.append(f"flag_deltas has unexpected keys: {sorted(unexpected)}")

    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate.py <path_to_tuning.json>")
        sys.exit(1)

    try:
        validate_tuning_file(sys.argv[1])
        print(f"{sys.argv[1]} is valid.")
    except TuningValidationError as e:
        print(f"{sys.argv[1]} FAILED validation:")
        print(e)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"{sys.argv[1]} is not valid JSON: {e}")
        sys.exit(1)