import pytest

from interpreter.parser import InterpreterParseError, parse_turn_flags


def test_parses_clean_json():
    raw = '{"validating": 0.8, "silence_tolerance": 0.0, "premature_reassurance": 0.0, "jargon": 0.0, "logistics_first": 0.0, "interruption": 0.0}'
    flags = parse_turn_flags(raw)
    assert flags.validating == 0.8
    assert flags.interruption == 0.0


def test_strips_markdown_code_fence():
    raw = '```json\n{"validating": 0.5, "silence_tolerance": 0.0, "premature_reassurance": 0.0, "jargon": 0.0, "logistics_first": 0.0, "interruption": 0.0}\n```'
    flags = parse_turn_flags(raw)
    assert flags.validating == 0.5


def test_missing_key_raises():
    raw = '{"validating": 0.5, "silence_tolerance": 0.0, "premature_reassurance": 0.0, "jargon": 0.0, "logistics_first": 0.0}'
    with pytest.raises(InterpreterParseError, match="missing"):
        parse_turn_flags(raw)


def test_out_of_range_value_raises():
    raw = '{"validating": 1.5, "silence_tolerance": 0.0, "premature_reassurance": 0.0, "jargon": 0.0, "logistics_first": 0.0, "interruption": 0.0}'
    with pytest.raises(InterpreterParseError, match="between 0 and 1"):
        parse_turn_flags(raw)


def test_non_numeric_value_raises():
    raw = '{"validating": "high", "silence_tolerance": 0.0, "premature_reassurance": 0.0, "jargon": 0.0, "logistics_first": 0.0, "interruption": 0.0}'
    with pytest.raises(InterpreterParseError, match="must be a number"):
        parse_turn_flags(raw)


def test_garbage_input_raises():
    with pytest.raises(InterpreterParseError):
        parse_turn_flags("I think the score is pretty high, around 0.8")