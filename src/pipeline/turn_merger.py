import asyncio
from datetime import datetime, timezone

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipeline.timing import TurnTiming, words_from_riva_result


class TurnMerger(FrameProcessor):
    def __init__(self, on_event=None, wait_s: float = 0.8, race_s: float = 0.1):
        super().__init__()
        self.turn_open = False
        self.awaiting_final = False
        self.pending_interim = False
        self.fragments: list[str] = []
        # Word timings from every merged fragment. Riva's times count from the
        # start of the audio stream, so gaps between fragments (often the
        # hesitation pauses) come out right too.
        self.words = []
        self.wait_s = wait_s
        self.race_s = race_s
        self.wait_task: asyncio.Task | None = None
        self.on_event = on_event or (lambda *a, **k: None)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            if not (self.awaiting_final and self.pending_interim):
                self._cancel_wait()
                self.awaiting_final = False
                self.turn_open = True
            await self.push_frame(frame, direction)

        elif isinstance(frame, InterimTranscriptionFrame):
            if frame.text.strip():
                self.pending_interim = True
            await self.push_frame(frame, direction)

        elif isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            self.pending_interim = False
            if self.turn_open:
                if text:
                    self.fragments.append(text)
                    self.words.extend(words_from_riva_result(frame.result))
                    self.on_event("held fragment", repr(text))
            elif self.awaiting_final:
                if text:
                    self.fragments.append(text)
                    self.words.extend(words_from_riva_result(frame.result))
                    self.on_event("held fragment (after stop)", repr(text))
                self._cancel_wait()
                await self._flush(direction)
            else:
                self.on_event("late final passed through", repr(text))
                await self.push_frame(frame, direction)

        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.turn_open = False
            await self.push_frame(frame, direction)
            if self.fragments and not self.pending_interim:
                await self._flush(direction)
            else:
                self.awaiting_final = True
                if self.pending_interim:
                    self.on_event("waiting for in-flight interim")
                    delay = self.wait_s
                else:
                    delay = self.race_s
                self.wait_task = asyncio.create_task(self._flush_after_wait(direction, delay))

        else:
            await self.push_frame(frame, direction)

    async def _flush_after_wait(self, direction: FrameDirection, delay: float):
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self.wait_task = None
        self.on_event("wait expired")
        await self._flush(direction)

    async def _flush(self, direction: FrameDirection):
        merged = " ".join(self.fragments).strip()
        words = self.words
        self.fragments = []
        self.words = []
        self.awaiting_final = False
        self.pending_interim = False
        if not merged:
            self.on_event("turn closed with no text")
            return
        self.on_event("merged final", repr(merged))
        await self.push_frame(
            TranscriptionFrame(
                text=merged,
                user_id="learner",
                timestamp=datetime.now(timezone.utc).isoformat(),
                result=TurnTiming(words=words),
                finalized=True,
            ),
            direction,
        )

    def _cancel_wait(self):
        if self.wait_task and not self.wait_task.done():
            self.wait_task.cancel()
        self.wait_task = None

    async def cleanup(self):
        await super().cleanup()
        self._cancel_wait()