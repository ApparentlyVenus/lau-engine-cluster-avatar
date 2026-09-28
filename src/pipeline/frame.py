from dataclasses import dataclass

from pipecat.frames.frames import Frame


@dataclass
class TurnStartedFrame(Frame):
    """Sent as soon as a learner turn is final, before the interpreter returns.

    predicted_state is the state the turn would produce if the interpreter
    returned no flags. The renderer starts on it speculatively.
    """
    turn_id: int
    predicted_state: object
    learner_transcript: str
    filler_line: str | None = None
    history: list | None = None


@dataclass
class StateUpdatedFrame(Frame):
    state: object
    learner_transcript: str
    escalated: bool
    filler_line: str | None = None
    history: list | None = None
    turn_id: int | None = None
