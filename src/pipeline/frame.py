from dataclasses import dataclass

from pipecat.frames.frames import Frame


@dataclass
class StateUpdatedFrame(Frame):
    state: object
    learner_transcript: str
    escalated: bool
    filler_line: str | None = None