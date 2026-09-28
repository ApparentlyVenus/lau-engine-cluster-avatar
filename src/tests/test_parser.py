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


def test_missing_keys_default_to_zero():
    flags = parse_turn_flags('{"validating": 0.5}')
    assert flags.validating == 0.5
    assert flags.interruption == 0.0
    assert flags.disrespect == 0.0


def test_empty_object_is_all_zero():
    flags = parse_turn_flags("{}")
    assert all(v == 0.0 for v in flags.__dict__.values())


def test_unknown_key_raises():
    with pytest.raises(InterpreterParseError, match="unknown keys"):
        parse_turn_flags('{"validating": 0.5, "empathy": 0.9}')


def test_trailing_prose_is_ignored():
    flags = parse_turn_flags('{"validating": 0.7}\nThe learner acknowledged her fear.')
    assert flags.validating == 0.7


def test_answers_question_discounts_logistics_only():
    flags = parse_turn_flags('{"logistics_first": 0.8, "jargon": 0.6, "answers_question": 1.0}')
    assert flags.logistics_first == 0.0
    assert flags.jargon == 0.6


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