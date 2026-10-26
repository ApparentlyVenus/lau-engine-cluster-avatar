from dataclasses import dataclass

# Behaviours with trust/saturation deltas in the tuning file.
BEHAVIOUR_FLAGS = (
    "validating",
    "premature_reassurance",
    "jargon",
    "logistics_first",
    "silence_tolerance",
    "interruption",
    "disrespect",
)


@dataclass
class TurnFlags:
    validating: float = 0.0
    premature_reassurance: float = 0.0
    jargon: float = 0.0
    logistics_first: float = 0.0
    silence_tolerance: float = 0.0
    interruption: float = 0.0
    disrespect: float = 0.0
    # Not behaviours: events the interpreter also reports.
    answers_question: float = 0.0
    discloses_news: float = 0.0

    def behaviours(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in BEHAVIOUR_FLAGS}
