from dataclasses import dataclass


@dataclass
class TurnFlags:
    validating: float = 0.0
    premature_reassurance: float = 0.0
    jargon: float = 0.0
    logistics_first: float = 0.0
    silence_tolerance: float = 0.0
    interruption: float = 0.0
    disrespect: float = 0.0
