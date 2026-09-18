from dataclasses import dataclass


@dataclass
class TranscriptEvent:
    text: str
    is_final: bool
    stability: float