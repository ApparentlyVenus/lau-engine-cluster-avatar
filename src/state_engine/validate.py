import json
import sys

REQUIRED_FLAGS = [
    "validating",
    "silence_tolerance",
    "premature_reassurance",
    "jargon",
    "logistics_first",
    "interruption",
    "disrespect"
]

VALID_EMOTIONS = {"NONE", "SHOCK", "ANGER", "GRIEF", "FEAR", "BARGAINING", "CALM"}
VALID_DEFENSE_MODES = {"NONE", "SARCASM", "INTELLECTUALIZING", "MINIMIZING"}


class TuningValidationError(Exception):
    pass


TOP_LEVEL_KEYS = {
    "scenario", "severity_scale", "audio_tags", "personality", "interruption",
    "initial_state", "flag_deltas", "timing", "voice", "arc", "speech",
}
ARC_KEYS = {
    "disclosure", "shock_peak", "shock_decay", "shock_relief", "shock_prolong", "pre_news_anxiety",
    "weights", "competence_deltas", "walkout_trust", "walkout_turns",
}
COMPETENCE_KEYS = {
    "validating", "silence_tolerance", "premature_reassurance", "jargon", "logistics_first",
    "interruption", "disrespect", "answers_question",
}
SPEECH_KEYS = {"reply_delay_s", "speed", "stability", "style"}
TIMING_KEYS = {
    "pause_threshold_s", "slow_wpm", "fast_wpm", "min_words_for_rate",
    "talk_over_min_bot_speaking_s", "talk_over_flag", "commit_after_s", "commit_after_unfinished_s",
}
VOICE_KEYS = {"voice_id", "model", "stability"}


def validate_tuning_file(path: str) -> None:
    with open(path, "r") as f:
        tuning = json.load(f)
    errors = validate_tuning(tuning)
    if errors:
        raise TuningValidationError("\n".join(errors))


def validate_tuning(tuning) -> list[str]:
    """Every problem in a character file, as a list of messages. Empty = valid."""
    if not isinstance(tuning, dict):
        return ["The file must be a JSON object"]
    errors = []
    unknown = set(tuning) - TOP_LEVEL_KEYS
    if unknown:
        errors.append(f"Unknown top-level keys: {sorted(unknown)}")
    for check in (
        _validate_scenario, _validate_severity_scale, _validate_audio_tags, _validate_personality,
        _validate_interruption, _validate_initial_state, _validate_flag_deltas, _validate_timing, _validate_voice,
        _validate_arc, _validate_speech,
    ):
        try:
            errors += check(tuning)
        except (TypeError, AttributeError, KeyError) as e:
            # A value of the wrong type (a string where a number belongs...).
            errors.append(f"{check.__name__.removeprefix('_validate_')}: wrong value type ({e})")
    return errors


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_scenario(tuning: dict) -> list[str]:
    if "scenario" not in tuning:
        return ["Missing top-level key: scenario"]
    scenario = tuning["scenario"]
    errors = []
    for key in ("patient_name", "age", "prompt"):
        if key not in scenario:
            errors.append(f"Missing scenario.{key}")
    if "age" in scenario and (not isinstance(scenario["age"], int) or isinstance(scenario["age"], bool)):
        errors.append("scenario.age must be an integer")
    if "patient_name" in scenario and (not isinstance(scenario["patient_name"], str) or not scenario["patient_name"].strip()):
        errors.append("scenario.patient_name must not be empty")
    for key in ("prompt", "clinical_facts"):
        if key in scenario and not isinstance(scenario[key], str):
            errors.append(f"scenario.{key} must be text")
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

    for key in ("trust_penalty", "saturation_penalty"):
        if key in personality and (not _num(personality[key]) or not -1.0 <= personality[key] <= 1.0):
            errors.append(f"personality.{key} must be a number between -1 and 1")

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

    if "competence" in init and (not _num(init["competence"]) or not 0.0 <= init["competence"] <= 1.0):
        errors.append("initial_state.competence must be between 0 and 1")

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
        for key in ("trust", "saturation"):
            if key in rule and (not _num(rule[key]) or not -1.0 <= rule[key] <= 1.0):
                errors.append(f"flag_deltas.{flag_name}.{key} must be a number between -1 and 1")

    unexpected = set(deltas.keys()) - set(REQUIRED_FLAGS)
    if unexpected:
        errors.append(f"flag_deltas has unexpected keys: {sorted(unexpected)}")

    return errors


def _validate_timing(tuning: dict) -> list[str]:
    """Optional section; defaults live in pipeline.timing.TimingConfig."""
    timing = tuning.get("timing")
    if timing is None:
        return []
    if not isinstance(timing, dict):
        return ["timing must be an object"]
    errors = []
    unknown = set(timing) - TIMING_KEYS
    if unknown:
        errors.append(f"timing has unknown keys: {sorted(unknown)}")
    for key, value in timing.items():
        if key in TIMING_KEYS and (not _num(value) or value < 0):
            errors.append(f"timing.{key} must be a non-negative number")
    if "min_words_for_rate" in timing and not isinstance(timing["min_words_for_rate"], int):
        errors.append("timing.min_words_for_rate must be a whole number")
    if _num(timing.get("slow_wpm")) and _num(timing.get("fast_wpm")) and timing["slow_wpm"] >= timing["fast_wpm"]:
        errors.append("timing.slow_wpm must be below timing.fast_wpm")
    if (_num(timing.get("commit_after_s")) and _num(timing.get("commit_after_unfinished_s"))
            and timing["commit_after_unfinished_s"] < timing["commit_after_s"]):
        errors.append("timing.commit_after_unfinished_s must be at least timing.commit_after_s")
    return errors


def _validate_voice(tuning: dict) -> list[str]:
    """Optional section (only needed with TTS). An empty voice_id is allowed
    here so a character can be drafted before a voice is picked."""
    voice = tuning.get("voice")
    if voice is None:
        return []
    if not isinstance(voice, dict):
        return ["voice must be an object"]
    errors = []
    unknown = set(voice) - VOICE_KEYS
    if unknown:
        errors.append(f"voice has unknown keys: {sorted(unknown)}")
    if "voice_id" in voice and not isinstance(voice["voice_id"], str):
        errors.append("voice.voice_id must be a string")
    if "model" in voice and (not isinstance(voice["model"], str) or not voice["model"].startswith("eleven_")):
        errors.append("voice.model must be an ElevenLabs model id such as eleven_v3_conversational")
    stability = voice.get("stability")
    if stability is not None and (not _num(stability) or not 0.0 <= stability <= 1.0):
        errors.append("voice.stability must be between 0 and 1")
    return errors


def _unit(errors: list, path: str, value, lo: float = 0.0, hi: float = 1.0):
    if not _num(value) or not lo <= value <= hi:
        errors.append(f"{path} must be a number between {lo:g} and {hi:g}")


def _validate_arc(tuning: dict) -> list[str]:
    """Optional section; defaults live in state_engine.config.ArcConfig."""
    arc = tuning.get("arc")
    if arc is None:
        return []
    if not isinstance(arc, dict):
        return ["arc must be an object"]
    errors = []
    unknown = set(arc) - ARC_KEYS
    if unknown:
        errors.append(f"arc has unknown keys: {sorted(unknown)}")
    disclosure = arc.get("disclosure", {})
    if not isinstance(disclosure, dict) or set(disclosure) - {"trust", "saturation"}:
        errors.append("arc.disclosure must be an object with trust and/or saturation")
    else:
        for k, v in disclosure.items():
            _unit(errors, f"arc.disclosure.{k}", v, -1, 1)
    for key in ("shock_peak", "shock_decay", "pre_news_anxiety", "walkout_trust"):
        if key in arc:
            _unit(errors, f"arc.{key}", arc[key])
    if "walkout_turns" in arc and (not isinstance(arc["walkout_turns"], int) or arc["walkout_turns"] < 0):
        errors.append("arc.walkout_turns must be a whole number, 0 to disable")
    if "weights" in arc:
        w = arc["weights"]
        if not isinstance(w, dict):
            errors.append("arc.weights must be an object")
        else:
            for k, v in w.items():
                if k not in VALID_EMOTIONS or k == "NONE":
                    errors.append(f"arc.weights has invalid emotion: {k}")
                _unit(errors, f"arc.weights.{k}", v, 0, 3)
    for group, allowed in (("shock_relief", COMPETENCE_KEYS), ("shock_prolong", COMPETENCE_KEYS), ("competence_deltas", COMPETENCE_KEYS)):
        if group in arc:
            d = arc[group]
            if not isinstance(d, dict):
                errors.append(f"arc.{group} must be an object")
                continue
            for k, v in d.items():
                if k not in allowed:
                    errors.append(f"arc.{group} has unknown flag: {k}")
                _unit(errors, f"arc.{group}.{k}", v, -1, 1)
    return errors


def _validate_speech(tuning: dict) -> list[str]:
    """Optional section; defaults live in state_engine.config.DEFAULT_SPEECH."""
    speech = tuning.get("speech")
    if speech is None:
        return []
    if not isinstance(speech, dict):
        return ["speech must be an object"]
    errors = []
    for emotion, prof in speech.items():
        if emotion not in VALID_EMOTIONS or emotion == "NONE":
            errors.append(f"speech has invalid emotion: {emotion}")
            continue
        if not isinstance(prof, dict):
            errors.append(f"speech.{emotion} must be an object")
            continue
        unknown = set(prof) - SPEECH_KEYS
        if unknown:
            errors.append(f"speech.{emotion} has unknown keys: {sorted(unknown)}")
        if "reply_delay_s" in prof:
            _unit(errors, f"speech.{emotion}.reply_delay_s", prof["reply_delay_s"], 0, 4)
        if "speed" in prof:
            _unit(errors, f"speech.{emotion}.speed", prof["speed"], 0.7, 1.2)
        if prof.get("stability") is not None:
            _unit(errors, f"speech.{emotion}.stability", prof["stability"])
        if "style" in prof and not isinstance(prof["style"], str):
            errors.append(f"speech.{emotion}.style must be text")
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