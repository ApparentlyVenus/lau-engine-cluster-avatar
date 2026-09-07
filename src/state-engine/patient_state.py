from enum import Enum
from dataclasses import dataclass

class EmotionMode(Enum):
    NONE = 1
    SHOCK = 2
    ANGER = 3
    GRIEF = 4
    FEAR = 5
    BARGAINING = 6

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