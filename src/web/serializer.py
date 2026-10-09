"""Wire format between the browser page and the pipeline.

Browser -> server
    binary: raw PCM16 mono at 16 kHz (the learner's mic)
Server -> browser
    binary: raw PCM16 mono at 24 kHz (her voice)
    text:   JSON events, {"type": ...}: transcript, her line, state, latency,
            and {"type": "clear"} when the learner barges in (drop queued audio)
"""

import json

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

IN_SAMPLE_RATE = 16000
OUT_SAMPLE_RATE = 24000


class PcmJsonSerializer(FrameSerializer):
    async def serialize(self, frame: Frame) -> str | bytes | None:
        if self.should_ignore_frame(frame):
            return None
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "clear"})
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return json.dumps(frame.message, default=str)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            if not data:
                return None
            return InputAudioRawFrame(audio=bytes(data), sample_rate=IN_SAMPLE_RATE, num_channels=1)
        return None  # the page sends no control messages yet
