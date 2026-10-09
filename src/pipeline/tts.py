"""TTS for her voice. Two options, picked with TTS_MODEL:

eleven_v3_conversational (default) / eleven_v3
    Performs the bracket tags ([voice breaking], [pause]...). Only reachable
    through ElevenLabs' Text-to-Dialogue WebSocket, which needs that API enabled
    for your workspace. Pipecat aggregates its input by sentence, so the
    renderer's early comma-chunk waits for the end of its sentence here.

eleven_flash_v2_5 (or any Flash/Turbo/Multilingual model)
    Fastest (~75 ms model time) but reads tags out loud, so they are stripped
    first and [pause] becomes "...". Text is streamed token by token, so the
    early first chunk goes out immediately.

ELEVENLABS_STABILITY, optional: lower is more expressive, higher is steadier.
"""

import os
import re

from pipecat.frames.frames import Frame, InterimTranscriptionFrame, TextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.tts_service import TextAggregationMode

from tracing import mark

DEFAULT_MODEL = "eleven_v3_conversational"
TAG = re.compile(r"\[([^\]]*)\]")


def strip_tags(text: str) -> str:
    def replace(m: re.Match) -> str:
        return "..." if m.group(1).strip().lower() == "pause" else ""

    out = TAG.sub(replace, text)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([,.?!])", r"\1", out)
    out = re.sub(r"(\.\.\.\s*){2,}", "... ", out)
    return out.strip()


class TagStripper(FrameProcessor):
    """Removes audio tags from her lines before a TTS model that cannot perform them."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if type(frame) is TextFrame:
            text = strip_tags(frame.text)
            if not text or text == "...":
                return
            frame = TextFrame(text=text + " ")
        elif isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
            pass
        await self.push_frame(frame, direction)


def is_v3(model: str) -> bool:
    return model.startswith("eleven_v3")


def build_tts(model: str | None = None) -> list[FrameProcessor]:
    """Returns the processors to place where TTS goes (one or two)."""
    model = model or os.environ.get("TTS_MODEL", DEFAULT_MODEL)
    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice = os.environ["ELEVENLABS_VOICE_ID"]
    stability = os.environ.get("ELEVENLABS_STABILITY")

    if is_v3(model):
        from pipecat.services.elevenlabs.dialogue.tts import ElevenLabsDialogueTTSService

        settings = ElevenLabsDialogueTTSService.Settings(model=model, voice=voice)
        if stability:
            settings.stability = float(stability)
        mark("tts", "ElevenLabs", f"{model} via Text-to-Dialogue (tags performed)")
        return [ElevenLabsDialogueTTSService(api_key=api_key, settings=settings)]

    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    settings = ElevenLabsTTSService.Settings(model=model, voice=voice)
    if stability:
        settings.stability = float(stability)
    mark("tts", "ElevenLabs", f"{model} streaming tokens (tags stripped)")
    return [
        TagStripper(),
        ElevenLabsTTSService(
            api_key=api_key,
            settings=settings,
            auto_mode=False,
            text_aggregation_mode=TextAggregationMode.TOKEN,
        ),
    ]
