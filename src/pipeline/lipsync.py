"""Word timings for the 3D patient's lip sync.

ElevenLabs returns, with the audio, when each word starts. Pipecat turns those
into word timestamps relative to the start of each TTS context (one reply).
This module hands them to the browser as

    {"type": "word", "w": "Cancer?", "s": 52800, "d": 9600}

where `s` is the word's position in the patient's audio stream, in samples at
24 kHz, counted from the start of the session (or from the last barge-in), and
`d` its length in samples. The page counts the audio samples it receives the
same way, so it can line each word up with the audio it belongs to, however
far ahead of playback the audio arrives.

Two pieces:
  * `watch_word_timestamps(tts)` makes the TTS service push a `WordTimingFrame`
    for every word, in playback order with its audio.
  * `LipSyncTap`, placed right after the TTS service, counts audio samples and
    turns each `WordTimingFrame` into a "word" event.
"""

from dataclasses import dataclass

from loguru import logger
from pipecat.frames.frames import (
    DataFrame,
    Frame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

OUT_SAMPLE_RATE = 24000
MAX_WORD_S = 1.0  # a gap longer than this is a pause, not a long word
LAST_WORD_S_PER_CHAR = 0.07
LAST_WORD_MAX_S = 0.6


@dataclass
class WordTimingFrame(DataFrame):
    """One spoken word: seconds from the start of its TTS context."""

    word: str = ""
    seconds: float = 0.0
    context_id: str | None = None


def watch_word_timestamps(tts) -> bool:
    """Make `tts` push a WordTimingFrame for each word it times.

    Wraps Pipecat's internal `_add_word_timestamps`, which TTS services call
    in playback order, interleaved with the audio of the same context. While
    the service is still waiting for a context's first audio it caches words
    and calls this again once the audio starts, so cached calls are skipped
    here to avoid sending a word twice. Returns False if this Pipecat version
    has no such hook (lip sync then falls back to the page's mouth motion).
    """
    original = getattr(tts, "_add_word_timestamps", None)
    if original is None or not hasattr(tts, "_initial_word_timestamp"):
        logger.warning("lip sync: this Pipecat version exposes no word timestamps")
        return False

    async def add_word_timestamps(word_times, context_id=None, includes_inter_frame_spaces=False):
        if tts._initial_word_timestamp != -1:
            for word, seconds in word_times:
                if word.strip():
                    await tts.push_frame(WordTimingFrame(word=word.strip(), seconds=float(seconds), context_id=context_id))
        await original(word_times, context_id, includes_inter_frame_spaces)

    tts._add_word_timestamps = add_word_timestamps
    return True


class LipSyncTap(FrameProcessor):
    """Counts the patient's audio and sends each word's position in it."""

    def __init__(self, sample_rate: int = OUT_SAMPLE_RATE, **kwargs):
        super().__init__(**kwargs)
        self._rate = sample_rate
        self._reset()

    def _reset(self):
        self._samples = 0  # audio samples (at self._rate) passed downstream
        self._context_start: dict[str, int] = {}  # context id -> sample its audio began at
        self._waiting: dict[str, list[WordTimingFrame]] = {}  # words that beat their audio here
        self._held: tuple[str, int] | None = None  # last word, sent once its length is known

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            # The transport drops the audio it still holds; the page resets its count on "clear".
            self._reset()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, WordTimingFrame):
            await self._word(frame)
            return  # internal: never goes further down the pipeline

        if isinstance(frame, OutputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            ctx = getattr(frame, "context_id", None)
            if ctx is not None and ctx not in self._context_start:
                self._context_start[ctx] = self._samples
                for w in self._waiting.pop(ctx, []):
                    await self._word(w)
            channels = max(1, frame.num_channels)
            n = len(frame.audio) // (2 * channels)
            self._samples += round(n * self._rate / max(1, frame.sample_rate))

        elif isinstance(frame, TTSStoppedFrame):
            await self._flush_held()

        await self.push_frame(frame, direction)

    async def _word(self, w: WordTimingFrame):
        start = self._context_start.get(w.context_id) if w.context_id is not None else self._samples
        if start is None:
            self._waiting.setdefault(w.context_id, []).append(w)
            return
        position = start + round(w.seconds * self._rate)
        if self._held:
            word, at = self._held
            gap = position - at
            length = gap if 0 < gap <= MAX_WORD_S * self._rate else self._guess_length(word)
            await self._send(word, at, length)
        self._held = (w.word, position)

    async def _flush_held(self):
        if self._held:
            word, at = self._held
            await self._send(word, at, self._guess_length(word))
            self._held = None

    def _guess_length(self, word: str) -> int:
        return round(min(LAST_WORD_MAX_S, max(0.15, len(word) * LAST_WORD_S_PER_CHAR)) * self._rate)

    async def _send(self, word: str, at: int, length: int):
        message = {"type": "word", "w": word, "s": at, "d": length}
        await self.push_frame(OutputTransportMessageUrgentFrame(message=message), FrameDirection.DOWNSTREAM)
