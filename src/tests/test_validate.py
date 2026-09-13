import json

import pytest

from state_engine.validate import TuningValidationError, validate_tuning_file


def write(tmp_path, data):
    path = tmp_path / "tuning.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_valid_file_passes(tuning_file):
    validate_tuning_file(tuning_file)


def test_missing_scenario_fails(tmp_path, persona_dict):
    del persona_dict["scenario"]
    path = write(tmp_path, persona_dict)
    with pytest.raises(TuningValidationError, match="scenario"):
        validate_tuning_file(path)


def test_missing_flag_delta_fails(tmp_path, persona_dict):
    del persona_dict["flag_deltas"]["jargon"]
    path = write(tmp_path, persona_dict)
    with pytest.raises(TuningValidationError, match="jargon"):
        validate_tuning_file(path)


def test_unexpected_flag_delta_key_fails(tmp_path, persona_dict):
    persona_dict["flag_deltas"]["made_up_flag"] = {"trust": 0, "saturation": 0, "acknowledges": False}
    path = write(tmp_path, persona_dict)
    with pytest.raises(TuningValidationError, match="unexpected"):
        validate_tuning_file(path)


def test_leftover_unacknowledged_turns_fails(tmp_path, persona_dict):
    persona_dict["initial_state"]["unacknowledged_turns"] = 0
    path = write(tmp_path, persona_dict)
    with pytest.raises(TuningValidationError, match="unacknowledged_turns"):
        validate_tuning_file(path)


def test_invalid_defense_mode_fails(tmp_path, persona_dict):
    persona_dict["personality"]["preferred_defense_mode"] = "NONE"
    path = write(tmp_path, persona_dict)
    with pytest.raises(TuningValidationError, match="preferred_defense_mode"):
        validate_tuning_file(path)


def test_band_min_greater_than_max_fails(tmp_path, persona_dict):
    persona_dict["severity_scale"]["trust_bands"]["trusting"]["min"] = 0.9
    persona_dict["severity_scale"]["trust_bands"]["trusting"]["max"] = 0.5
    path = write(tmp_path, persona_dict)
    with pytest.raises(TuningValidationError, match="min > max"):
        validate_tuning_file(path)


def test_out_of_range_threshold_fails(tmp_path, persona_dict):
    persona_dict["personality"]["defense_trigger_trust"] = 1.5
    path = write(tmp_path, persona_dict)
    with pytest.raises(TuningValidationError, match="defense_trigger_trust"):
        validate_tuning_file(path)


def test_invalid_json_raises_decode_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        validate_tuning_file(str(path))