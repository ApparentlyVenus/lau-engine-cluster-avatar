from dataclasses import dataclass

@dataclass
class TurnFlags:
    validating: float
    premature_reassurance: float
    jargon: float
    logistics_first: float
    silence_tolerance: float
    interruption: float