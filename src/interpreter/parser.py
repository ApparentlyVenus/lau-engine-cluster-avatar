import json

from state_engine.turn_flags import TurnFlags

REQUIRED_KEYS = [
    "validating",
    "silence_tolerance",
    "premature_reassurance",
    "jargon",
    "logistics_first",
    "interruption",
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

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise InterpreterParseError(f"Could not parse interpreter response as JSON: {e}\nRaw response: {raw_response}")

    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise InterpreterParseError(f"Interpreter response missing keys: {missing}\nRaw response: {raw_response}")

    for key in REQUIRED_KEYS:
        value = data[key]
        if not isinstance(value, (int, float)):
            raise InterpreterParseError(f"{key} must be a number, got {type(value)}")
        if not (0.0 <= value <= 1.0):
            raise InterpreterParseError(f"{key} must be between 0 and 1, got {value}")

    return TurnFlags(
        validating=float(data["validating"]),
        silence_tolerance=float(data["silence_tolerance"]),
        premature_reassurance=float(data["premature_reassurance"]),
        jargon=float(data["jargon"]),
        logistics_first=float(data["logistics_first"]),
        interruption=float(data["interruption"]),
    )