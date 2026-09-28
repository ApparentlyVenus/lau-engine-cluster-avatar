import json

from state_engine.turn_flags import TurnFlags

FLAG_NAMES = [
    "validating",
    "silence_tolerance",
    "premature_reassurance",
    "jargon",
    "logistics_first",
    "interruption",
    "disrespect",
]

ANSWER_KEY = "answers_question"
DISCOUNTED_FLAGS = ["logistics_first"]

class InterpreterParseError(Exception):
    pass


def _read_number(data: dict, name: str) -> float:
    value = data.get(name, 0.0)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InterpreterParseError(f"{name} must be a number, got {type(value)}")
    if not (0.0 <= value <= 1.0):
        raise InterpreterParseError(f"{name} must be between 0 and 1, got {value}")
    return float(value)


def parse_turn_flags(raw_response: str) -> TurnFlags:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json")
        cleaned = cleaned.strip()

    start = cleaned.find("{")
    if start == -1:
        raise InterpreterParseError(f"No JSON object in interpreter response\nRaw response: {raw_response}")

    try:
        data, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as e:
        raise InterpreterParseError(f"Could not parse interpreter response as JSON: {e}\nRaw response: {raw_response}")

    if not isinstance(data, dict):
        raise InterpreterParseError(f"Interpreter response must be a JSON object\nRaw response: {raw_response}")

    unknown = [key for key in data if key not in FLAG_NAMES and key != ANSWER_KEY]
    if unknown:
        raise InterpreterParseError(f"Interpreter response has unknown keys: {unknown}\nRaw response: {raw_response}")

    values = {name: _read_number(data, name) for name in FLAG_NAMES}

    answer_factor = 1.0 - _read_number(data, ANSWER_KEY)
    for name in DISCOUNTED_FLAGS:
        values[name] *= answer_factor

    return TurnFlags(**values)