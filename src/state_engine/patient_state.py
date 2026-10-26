from enum import Enum
from dataclasses import dataclass

class EmotionMode(Enum):
    NONE = 1
    SHOCK = 2
    ANGER = 3
    GRIEF = 4
    FEAR = 5        # fear / anxiety: worry about what comes next
    BARGAINING = 6
    CALM = 7        # baseline guarded optimism, or settled problem-solving later

class DefenseMode(Enum):
    NONE = 1
    SARCASM = 2
    INTELLECTUALIZING = 3
    MINIMIZING = 4

@dataclass
class EmotionState:
    primary: EmotionMode
    secondary: EmotionMode
    blend_weight: float # 0-1, how much the secondary bleeds into the primary
    intensity: float # 0-1, overall strength

@dataclass
class DefenseState:
    mode: DefenseMode
    masking: EmotionMode # underlying emotion

@dataclass
class PatientState:
    trust: float
    saturation: float
    unacknowledged_turns: int
    turn_count: int
    emotion: EmotionState
    defense: DefenseState
    # How capable she thinks this doctor is (clear answers raise it; jargon,
    # empty reassurance and contempt lower it). Feeds her anxiety.
    competence: float = 0.6
    # Has the learner told her the result yet? The emotional arc (shock and
    # what follows) starts from that turn, not from the first turn.
    news_delivered: bool = False
    # Shock: set to its peak by the disclosure, then fades turn by turn,
    # faster when the learner gives her space, slower when they rush on.
    shock: float = 0.0
    # Consecutive turns with trust at the walk-out level, and whether she has
    # ended the consultation.
    low_trust_turns: int = 0
    ended: bool = False

    @property
    def satisfaction(self) -> float:
        """Derived, for display and reports: trusts the doctor, rates them, and
        is not overloaded."""
        return max(0.0, min(1.0, (self.trust + self.competence) / 2 * (1 - 0.5 * self.saturation)))