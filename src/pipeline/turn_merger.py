import asyncio
from datetime import datetime, timezone

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipeline.timing import TurnTiming, words_from_riva_result

# Riva's last transcript normally lands ~0.5 s after the learner stops.
SLOW_STT_S = 2.0
# Finals that arrive with no turn open (speech VAD missed the start of, or that
# came after her reply was released) are held this long for more, then sent
# as one turn. Without this, "I would like to tell you", "cancer", "mass"
# became three turns, each scored and answered.
LATE_HOLD_S = 1.0


class TurnMerger(FrameProcessor):
    def __init__(self, on_event=None, wait_s: float = 0.8, race_s: float = 0.1, gate=None):
        super().__init__()
        self.gate = gate
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
        # For the "no words came back" warning: did the learner start speaking
        # since the last flush, and did any words (interim or final) arrive?
        self.started = False
        self.heard_words = False
        # True while holding late finals (see LATE_HOLD_S).
        self.late_hold = False
        self.on_event = on_event or (lambda *a, **k: None)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            await self._reopen_if_pending()
            if not (self.awaiting_final and self.pending_interim):
                self._cancel_wait()
                self.awaiting_final = False
                self.late_hold = False
                self.turn_open = True
                if not self.fragments:
                    self.heard_words = False
                self.started = True
            await self.push_frame(frame, direction)

        elif isinstance(frame, InterimTranscriptionFrame):
            if frame.text.strip():
                self.pending_interim = True
                self.heard_words = True
            await self.push_frame(frame, direction)

        elif isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            self.pending_interim = False
            if text:
                self.heard_words = True
            if self.turn_open:
                if text:
                    self.fragments.append(text)
                    self.words.extend(words_from_riva_result(frame.result))
                    self.on_event("held fragment", repr(text))
            elif self.awaiting_final and self.late_hold:
                if text:
                    self.fragments.append(text)
                    self.words.extend(words_from_riva_result(frame.result))
                    self.on_event("late final held", repr(text))
                self._cancel_wait()
                self.wait_task = asyncio.create_task(self._flush_after_wait(direction, LATE_HOLD_S))
            elif self.awaiting_final:
                if text:
                    self.fragments.append(text)
                    self.words.extend(words_from_riva_result(frame.result))
                    self.on_event("held fragment (after stop)", repr(text))
                self._cancel_wait()
                await self._flush(direction)
            elif text and self.gate is not None and self.gate.can_reopen():
                # Speech that arrived after the turn closed but before she
                # answered belongs to the same turn.
                await self._reopen_if_pending()
                self.fragments.append(text)
                self.words.extend(words_from_riva_result(frame.result))
                self.on_event("late final merged", repr(text))
                await self._flush(direction)
            elif text:
                self.fragments.append(text)
                self.words.extend(words_from_riva_result(frame.result))
                self.on_event("late final held", repr(text))
                self._cancel_wait()
                self.awaiting_final = True
                self.late_hold = True
                self.wait_task = asyncio.create_task(self._flush_after_wait(direction, LATE_HOLD_S))

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
        self.late_hold = False
        started, self.started = self.started, False
        if not merged:
            if self.heard_words or not started:
                # The words already went out with the previous turn.
                self.on_event("turn closed with no new text")
                return
            # VAD heard sound but Riva sent no words at all. Once is a cough;
            # every turn means speech-to-text is down (src/tools/riva_check.py).
            self.on_event("turn closed with no text", "Riva returned nothing for this speech")
            await self.push_frame(
                OutputTransportMessageUrgentFrame(message={"type": "stt_empty"}), FrameDirection.DOWNSTREAM
            )
            return
        self.on_event("merged final", repr(merged))
        timing = TurnTiming(words=words)
        if self.gate is not None:
            timing.gate_turn = self.gate.turn_flushed(merged, [merged], words)
            lag = timing.gate_turn.stt_lag_s
            if lag > SLOW_STT_S:
                self.on_event("SLOW NETWORK", f"transcript arrived {lag:.1f}s after you stopped talking")
                await self.push_frame(
                    OutputTransportMessageUrgentFrame(message={"type": "network", "stt_lag_s": round(lag, 1)}),
                    FrameDirection.DOWNSTREAM,
                )
        await self.push_frame(
            TranscriptionFrame(
                text=merged,
                user_id="learner",
                timestamp=datetime.now(timezone.utc).isoformat(),
                result=timing,
                finalized=True,
            ),
            direction,
        )

    async def _reopen_if_pending(self):
        if self.gate is None:
            return
        turn = self.gate.reopen()
        if turn is None:
            return
        # Put the closed turn's words back in front of whatever comes next.
        self.fragments = turn.fragments + self.fragments
        self.words = turn.words + self.words
        await self.push_frame(
            OutputTransportMessageUrgentFrame(message={"type": "turn_reopened"}), FrameDirection.DOWNSTREAM
        )

    def _cancel_wait(self):
        if self.wait_task and not self.wait_task.done():
            self.wait_task.cancel()
        self.wait_task = None

    async def cleanup(self):
        await super().cleanup()
        self._cancel_wait()