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


class InterpreterParseError(Exception):
    pass


def parse_turn_flags(raw_response: str) -> TurnFlags:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
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

    unknown = [key for key in data if key not in FLAG_NAMES]
    if unknown:
        raise InterpreterParseError(f"Interpreter response has unknown keys: {unknown}\nRaw response: {raw_response}")

    values = {}
    for name in FLAG_NAMES:
        value = data.get(name, 0.0)
        if not isinstance(value, (int, float)):
            raise InterpreterParseError(f"{name} must be a number, got {type(value)}")
        if not (0.0 <= value <= 1.0):
            raise InterpreterParseError(f"{name} must be between 0 and 1, got {value}")
        values[name] = float(value)

    return TurnFlags(**values)