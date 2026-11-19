"""Typed turns: the doctor can type instead of speaking.

The page sends {"type": "say", "text": "..."} over the session WebSocket; the
serializer turns it into an InputTransportMessageFrame. This processor sits
right after the TimingTracker and replays the text as a spoken turn would
arrive at the TurnMerger (start, final transcript, stop), so it goes through
the same merging, turn gate, scoring and reply as speech.

It deliberately sits after the TimingTracker: a typed turn has no measured
timing (no pauses, speaking rate or gap after her line), and typing time must
not be read as the doctor leaving a silence.
"""

from datetime import datetime, timezone

from pipecat.frames.frames import (
    Frame,
    InputTransportMessageFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

import tracing
from tracing import mark

MAX_CHARS = 1000


class TypedTurnInput(FrameProcessor):
    def __init__(self, gate=None, timing_tracker=None, barge_in: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.gate = gate
        self.timing_tracker = timing_tracker
        self.barge_in = barge_in

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        message = frame.message if isinstance(frame, InputTransportMessageFrame) else None
        if isinstance(message, dict) and message.get("type") == "say":
            if direction == FrameDirection.DOWNSTREAM:
                text = str(message.get("text", "")).strip()[:MAX_CHARS]
                if text:
                    await self._say(text)
            return
        await self.push_frame(frame, direction)

    async def _say(self, text: str):
        mark("typed", "doctor typed", repr(text))
        tracing.begin_turn_if_idle()
        speaking = bool(self.timing_tracker and self.timing_tracker.bot_speaking)
        if speaking and self.barge_in:
            # Same as speaking over her with barge-in on: stop her audio and reply.
            await self.broadcast_interruption()
        if self.gate is not None:
            self.gate.learner_stopped()  # the turn gate counts its pause from now
        down = FrameDirection.DOWNSTREAM
        await self.push_frame(UserStartedSpeakingFrame(), down)
        await self.push_frame(
            TranscriptionFrame(
                text=text,
                user_id="learner",
                timestamp=datetime.now(timezone.utc).isoformat(),
                finalized=True,
            ),
            down,
        )
        await self.push_frame(UserStoppedSpeakingFrame(), down)
