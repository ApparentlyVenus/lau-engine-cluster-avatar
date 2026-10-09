import json
import os
import re
from dataclasses import dataclass, fields

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TextFrame,
    TranscriptionFrame,
)
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


@dataclass
class VoiceConfig:
    voice_id: str
    model: str = DEFAULT_MODEL
    stability: float | None = None

    @classmethod
    def from_tuning_file(cls, path: str) -> "VoiceConfig":
        with open(path) as f:
            raw = json.load(f).get("voice")
        if not raw or not str(raw.get("voice_id", "")).strip():
            raise ValueError(
                f"No voice for this patient: add \"voice\": {{\"voice_id\": \"...\"}} to {path}. "
                "Copy the ID from ElevenLabs > Voices > (voice menu) > Copy voice ID, or run with --no-tts."
            )
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown keys in tuning 'voice' section: {sorted(unknown)}")
        return cls(**raw)


def build_tts(voice: VoiceConfig, model_override: str | None = None) -> list[FrameProcessor]:
    """Returns the processors to place where TTS goes (one or two)."""
    model = model_override or voice.model
    api_key = os.environ["ELEVENLABS_API_KEY"]

    if is_v3(model):
        from pipecat.services.elevenlabs.dialogue.tts import (
            ElevenLabsDialogueTTSService,
        )

        settings = ElevenLabsDialogueTTSService.Settings(model=model, voice=voice.voice_id)
        if voice.stability is not None:
            settings.stability = voice.stability
        mark("tts", "ElevenLabs", f"{model}, voice {voice.voice_id} (tags performed)")
        return [ElevenLabsDialogueTTSService(api_key=api_key, settings=settings)]

    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    settings = ElevenLabsTTSService.Settings(model=model, voice=voice.voice_id)
    if voice.stability is not None:
        settings.stability = voice.stability
    mark("tts", "ElevenLabs", f"{model}, voice {voice.voice_id} (tags stripped)")
    return [
        TagStripper(),
        ElevenLabsTTSService(
            api_key=api_key,
            settings=settings,
            auto_mode=False,
            text_aggregation_mode=TextAggregationMode.TOKEN,
        ),
    ]