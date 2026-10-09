from dataclasses import dataclass

from pipecat.frames.frames import DataFrame, UninterruptibleFrame


# Both frames are uninterruptible: when the learner barges in, Pipecat flushes
# ordinary queued frames, and losing one of these would leave a speculative
# render waiting forever for a state that never arrives. The renderer decides
# what to do with a cancelled turn itself.


@dataclass
class TurnStartedFrame(UninterruptibleFrame, DataFrame):
    """Sent as soon as a learner turn is final, before the interpreter returns.

    predicted_state is the state the turn would produce from what is already
    known (no interpreter flags, plus anything measured, like talking over her).
    The renderer starts on it speculatively.
    """
    turn_id: int
    predicted_state: object
    learner_transcript: str
    filler_line: str | None = None
    history: list | None = None


@dataclass
class StateUpdatedFrame(UninterruptibleFrame, DataFrame):
    state: object
    learner_transcript: str
    escalated: bool
    filler_line: str | None = None
    history: list | None = None
    turn_id: int | None = None
