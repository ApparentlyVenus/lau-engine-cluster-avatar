import asyncio
import os
import time

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    OutputTransportMessageUrgentFrame,
    TextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

import llm_client
import tracing
from interpreter.claude import INTERPRETER_MODEL, call_interpreter
from interpreter.parser import parse_turn_flags
from interpreter.prompt import build_interpreter_message
from pipeline.frame import StateUpdatedFrame, TurnStartedFrame
from pipeline.interruption import pick_line, select_interrupt_category, should_interrupt
from pipeline.timing import (
    LiveTiming,
    TimingConfig,
    TurnTiming,
    annotate_transcript,
    timing_block,
    words_from_riva_result,
)
from renderer.claude import RENDERER_MODEL, stream_renderer
from renderer.prompt import build_renderer_message
from renderer.speculation import speculative_render
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state
from state_engine.turn_flags import TurnFlags
from tracing import mark

SPECULATIVE_RENDER = os.environ.get("SPECULATIVE_RENDER", "1") != "0"
RESUME_WITHIN_S = 0.5


async def send_ui(processor: FrameProcessor, message: dict):
    """Push an event to the browser UI. Transports without a UI ignore it."""
    await processor.push_frame(OutputTransportMessageUrgentFrame(message=message), FrameDirection.DOWNSTREAM)


def _band_name(bands: dict, band) -> str:
    return next((name for name, b in bands.items() if b is band), "")


def state_summary(persona, state) -> dict:
    scale = persona.severity_scale
    return {
        "trust": round(state.trust, 2),
        "trust_band": _band_name(scale.trust_bands, persona.trust_band(state.trust)),
        "saturation": round(state.saturation, 2),
        "saturation_band": _band_name(scale.saturation_bands, persona.saturation_band(state.saturation)),
        "emotion": state.emotion.primary.name,
        "undertone": state.emotion.secondary.name,
        "intensity": round(state.emotion.intensity, 2),
        "defense": state.defense.mode.name,
        "unacknowledged": state.unacknowledged_turns,
    }


async def _after(previous: asyncio.Task | None):
    """Wait for the previous task in a chain without inheriting its outcome.
    Our own cancellation still propagates."""
    if previous is not None and not previous.done():
        await asyncio.wait({previous})


class TimingTracker(FrameProcessor):
    """Measures timing from pipeline events: the gap after her line, and whether
    the learner started talking while she was audible.

    Place it after the turn processor so it sees UserStartedSpeakingFrame going
    down and BotStarted/StoppedSpeakingFrame coming up from the output.
    """

    def __init__(self, cfg: TimingConfig):
        super().__init__()
        self.cfg = cfg
        self.bot_speaking = False
        self.bot_started_at: float | None = None
        self.bot_stopped_at: float | None = None
        self.current: LiveTiming | None = None

    def take(self) -> LiveTiming:
        """Timing for the turn that just ended; resets for the next turn."""
        live = self.current or LiveTiming()
        self.current = None
        return live

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        now = time.monotonic()

        if isinstance(frame, BotStartedSpeakingFrame):
            if not self.bot_speaking:
                self.bot_speaking = True
                # Audio can stop and restart between sentences of one line.
                # A restart this soon is the same utterance: keep its start.
                resumed = self.bot_stopped_at is not None and now - self.bot_stopped_at < RESUME_WITHIN_S
                if not resumed or self.bot_started_at is None:
                    self.bot_started_at = now
                    mark("timing", "her audio started")
                tracing.audio_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self.bot_speaking:
                self.bot_speaking = False
                self.bot_stopped_at = now
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            tracing.begin_turn_if_idle()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            mark("vad", "learner stopped", key="last_word", overwrite=True)
        elif isinstance(frame, UserStartedSpeakingFrame) and self.current is None:
            # First start of a new learner turn. Later starts in the same turn
            # (resuming after a pause) keep this measurement.
            live = LiveTiming()
            if self.bot_speaking and self.bot_started_at is not None:
                audible = now - self.bot_started_at
                live.talked_over_her = audible >= self.cfg.talk_over_min_bot_speaking_s
                mark("timing", "learner over her" if live.talked_over_her else "learner started",
                     f"she had been speaking {audible:.1f}s")
            elif self.bot_stopped_at is not None:
                live.gap_after_her_line_s = now - self.bot_stopped_at
                mark("timing", "gap after her line", f"{live.gap_after_her_line_s:.1f}s")
            self.current = live

        await self.push_frame(frame, direction)


class InterpreterProcessor(FrameProcessor):
    """Scores each learner turn and updates her state.

    The API call runs in a background task, one turn after another. Pipecat
    cancels whatever a processor is doing when the learner barges in, and the
    learner's turn should still be scored: they did say it.
    """

    def __init__(
        self,
        persona: PersonaConfig,
        filler_getter=None,
        timing_tracker: TimingTracker | None = None,
        timing_cfg: TimingConfig | None = None,
    ):
        super().__init__()
        self.persona = persona
        self.state = build_initial_state(persona)
        self.history: list[str] = []
        self.filler_getter = filler_getter
        self.timing_tracker = timing_tracker
        self.timing_cfg = timing_cfg or TimingConfig()
        self.turn_id = 0
        self.last_task: asyncio.Task | None = None
        self._warned_no_words = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (UserStartedSpeakingFrame, InterimTranscriptionFrame)):
            # Re-open the API connection while the learner is still talking.
            llm_client.warm()
            if isinstance(frame, InterimTranscriptionFrame) and frame.text.strip():
                await send_ui(self, {"type": "learner_partial", "text": frame.text.strip()})

        if not isinstance(frame, TranscriptionFrame):
            await self.push_frame(frame, direction)
            return

        if not frame.text.strip():
            mark("interpreter", "empty final skipped")
            return

        self.turn_id += 1
        turn_id = self.turn_id
        mark("interpreter", "final frame in", key="final")

        timing = self._turn_timing(frame)
        annotated = annotate_transcript(frame.text, timing, self.timing_cfg)
        measured = timing_block(timing, self.timing_cfg)
        if annotated != frame.text:
            mark("timing", "annotated", repr(annotated))
        if measured:
            mark("timing", "measured", measured.replace("\n", " "))

        # Built before this turn's line is added to history.
        message = build_interpreter_message(self.persona, annotated, self.history, timing=measured)
        self.history.append(f"Learner: {frame.text}")
        filler_line = self.filler_getter() if self.filler_getter else None

        # Talking over her is measured, not judged, so it is known now and goes
        # into both the prediction and the final flags.
        measured_flags = TurnFlags(
            interruption=self.timing_cfg.talk_over_flag if timing.live.talked_over_her else 0.0
        )

        await send_ui(self, {
            "type": "learner_final",
            "text": frame.text,
            "annotated": annotated,
            "timing": measured,
        })

        predicted_state, _ = apply_turn(self.state, measured_flags, self.persona)
        await self.push_frame(
            TurnStartedFrame(
                turn_id=turn_id,
                predicted_state=predicted_state,
                learner_transcript=frame.text,
                filler_line=filler_line,
                history=self.history,
            ),
            direction,
        )

        previous = self.last_task

        async def run():
            await _after(previous)
            await self._interpret(turn_id, message, frame.text, filler_line, measured_flags, direction)

        self.last_task = asyncio.create_task(run())

    def _turn_timing(self, frame: TranscriptionFrame) -> TurnTiming:
        if isinstance(frame.result, TurnTiming):
            timing = frame.result
        else:  # a final that bypassed the merger still carries Riva's result
            timing = TurnTiming(words=words_from_riva_result(frame.result))
        if self.timing_tracker is not None:
            timing.live = self.timing_tracker.take()
        if not timing.words and not self._warned_no_words:
            self._warned_no_words = True
            mark("timing", "no word timings", "STT gave none; pauses inside turns are unavailable")
        return timing

    async def _interpret(self, turn_id, message, transcript, filler_line, measured_flags, direction):
        mark("interpreter", "API call ->", f"{INTERPRETER_MODEL}, {len(message)} chars")
        try:
            raw_response = await call_interpreter(message)
            mark("interpreter", "API call <-", repr(raw_response.strip()), key="interp_done")
            flags = parse_turn_flags(raw_response)
        except Exception as e:
            # Degrade quietly live: treat the turn as flagless rather than
            # dropping it. Loud in the log on purpose.
            mark("interpreter", "FAILED, no flags", repr(e), key="interp_done")
            flags = TurnFlags()

        flags.interruption = max(flags.interruption, measured_flags.interruption)

        self.state, escalated = apply_turn(self.state, flags, self.persona)
        mark(
            "state_engine",
            "apply_turn done",
            f"trust={self.state.trust:.2f} sat={self.state.saturation:.2f} escalated={escalated}",
            key="state_done",
        )
        await send_ui(self, {
            "type": "state",
            "flags": {k: v for k, v in flags.__dict__.items() if v},
            "escalated": escalated,
            **state_summary(self.persona, self.state),
        })

        await self.push_frame(
            StateUpdatedFrame(
                state=self.state,
                learner_transcript=transcript,
                escalated=escalated,
                filler_line=filler_line,
                history=self.history,
                turn_id=turn_id,
            ),
            direction,
        )

    async def cleanup(self):
        await super().cleanup()
        if self.last_task is not None and not self.last_task.done():
            self.last_task.cancel()


class RendererProcessor(FrameProcessor):
    """Renders her line. Work runs in background tasks so this processor never
    blocks on an API call, and turns are rendered strictly one after another.

    When the learner barges in (an InterruptionFrame), every turn started so far
    is cancelled: the reply in progress stops, and a reply whose state arrives
    later is never rendered. What she had already said goes into history marked
    as cut off, so the next line knows she was interrupted.
    """

    def __init__(self, persona: PersonaConfig, speculative: bool = SPECULATIVE_RENDER):
        super().__init__()
        self.persona = persona
        self.speculative = speculative
        self.pending: dict[int, asyncio.Future] = {}
        self.last_task: asyncio.Task | None = None
        self.tasks: set[asyncio.Task] = set()
        self.hits = 0
        self.misses = 0
        self.latest_turn = 0
        self.cancel_upto = 0
        # The render in progress: (history list, chunks sent so far)
        self.active: tuple[list, list[str]] | None = None
        # Her audio can still be playing after the render finished.
        self.bot_speaking = False
        self.last_history: list | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TurnStartedFrame):
            self.latest_turn = max(self.latest_turn, frame.turn_id)
            if self.speculative:
                future = asyncio.get_running_loop().create_future()
                self.pending[frame.turn_id] = future
                self._chain(self._render_speculative(frame, future, direction))

        elif isinstance(frame, StateUpdatedFrame):
            turn_id = frame.turn_id
            future = self.pending.pop(turn_id, None) if turn_id is not None else None
            if turn_id is not None and turn_id <= self.cancel_upto:
                mark("renderer", "skipped", f"turn {turn_id} was cut off by the learner")
            elif future is not None:
                if not future.done():
                    future.set_result(frame)
            else:
                self.latest_turn = max(self.latest_turn, turn_id or 0)
                self._chain(self._render_direct(frame, direction))

        elif isinstance(frame, InterruptionFrame):
            await self._cut_off()
            await self.push_frame(frame, direction)

        elif isinstance(frame, (BotStartedSpeakingFrame, BotStoppedSpeakingFrame)):
            self.bot_speaking = isinstance(frame, BotStartedSpeakingFrame)
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    async def _cut_off(self):
        if self.active is None and self.bot_speaking and self.last_history:
            # Fully generated but still being spoken: the learner did not hear
            # all of it, and the next line should know she was cut off.
            last = self.last_history[-1]
            if last.startswith("Patient: ") and not last.endswith("(cut off by the learner)"):
                self.last_history[-1] = last + " (cut off by the learner)"
                mark("renderer", "CUT OFF", "while her audio was playing")
                await send_ui(self, {"type": "cut_off"})
        if self.latest_turn <= self.cancel_upto and self.active is None:
            return  # nothing in flight
        self.cancel_upto = self.latest_turn
        if self.active is not None:
            history, chunks = self.active
            self.active = None
            if chunks:
                history.append(f"Patient: {' '.join(chunks)}- (cut off by the learner)")
                self.last_history = history
            mark("renderer", "CUT OFF", f"{len(chunks)} chunk(s) already sent")
            await send_ui(self, {"type": "cut_off"})
        for task in list(self.tasks):
            task.cancel()
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()

    def _chain(self, coro):
        previous = self.last_task

        async def run():
            try:
                await _after(previous)
                await coro
            except asyncio.CancelledError:
                coro.close()  # no "never awaited" warning if cancelled while queued
                raise
            except Exception as e:
                mark("renderer", "FAILED", repr(e))

        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        self.last_task = task

    def _message(self, state, transcript, history, filler_line) -> str:
        return build_renderer_message(
            self.persona, state, transcript, history=history, filler_line=filler_line
        )

    async def _emit(self, chunk: str, direction: FrameDirection):
        if self.active is not None:
            self.active[1].append(chunk)
        mark("renderer", "chunk -> TTS", repr(chunk), key="first_chunk")
        await send_ui(self, {"type": "patient_chunk", "text": chunk})
        await self.push_frame(TextFrame(text=chunk), direction)

    async def _finish(self, history: list, line: str, extra: str = ""):
        self.active = None
        mark("renderer", "stream done", extra, key="render_done")
        history.append(f"Patient: {line.strip()}")
        self.last_history = history
        await send_ui(self, {"type": "patient_done", "text": line.strip(), "note": extra})
        tracing.render_finished()

    async def _render_speculative(self, frame: TurnStartedFrame, future: asyncio.Future, direction):
        if frame.turn_id <= self.cancel_upto:
            return
        history = frame.history if frame.history is not None else []
        snapshot = list(history)
        self.active = (history, [])
        spec_message = self._message(frame.predicted_state, frame.learner_transcript, snapshot, frame.filler_line)
        mark("renderer", "spec API call ->", f"{RENDERER_MODEL}, {len(spec_message)} chars")

        async def real_message():
            update = await future
            return self._message(update.state, update.learner_transcript, snapshot, update.filler_line)

        async def emit(chunk):
            await self._emit(chunk, direction)

        line, hit = await speculative_render(spec_message, real_message(), stream_renderer, emit)
        if hit:
            self.hits += 1
        else:
            self.misses += 1
        await self._finish(history, line, f"speculation {'HIT' if hit else 'MISS'} ({self.hits} hit / {self.misses} miss)")

    async def _render_direct(self, frame: StateUpdatedFrame, direction):
        if frame.turn_id is not None and frame.turn_id <= self.cancel_upto:
            return
        history = frame.history if frame.history is not None else []
        self.active = (history, [])
        message = self._message(frame.state, frame.learner_transcript, history, frame.filler_line)
        mark("renderer", "API call ->", f"{RENDERER_MODEL}, {len(message)} chars")

        parts = []
        async for chunk in stream_renderer(message):
            await self._emit(chunk, direction)
            parts.append(chunk)
        await self._finish(history, " ".join(parts))

    async def cleanup(self):
        await super().cleanup()
        for task in list(self.tasks):
            task.cancel()
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()


class InterruptWatcherProcessor(FrameProcessor):
    def __init__(self, persona: PersonaConfig, state_getter):
        super().__init__()
        self.persona = persona
        self.get_state = state_getter
        self.turn_start_time = None
        self.last_interruption_time = 0.0
        self.interrupted_this_turn = False
        self.filler_line_this_turn = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            if self.turn_start_time is None:
                self.turn_start_time = time.monotonic()
                self.interrupted_this_turn = False
                self.filler_line_this_turn = None
                mark("interrupt", "first interim seen", repr(frame.text))

            if not self.interrupted_this_turn:
                seconds_speaking = time.monotonic() - self.turn_start_time
                seconds_since_last = time.monotonic() - self.last_interruption_time
                state = self.get_state()

                if should_interrupt(state, seconds_speaking, seconds_since_last, self.persona):
                    self.interrupted_this_turn = True
                    self.last_interruption_time = time.monotonic()
                    category = select_interrupt_category(state)
                    if category:
                        filler = pick_line(category)
                        self.filler_line_this_turn = filler
                        mark("interrupt", "FIRED", f"{category}: {filler!r}")
                        await send_ui(self, {"type": "patient_interjects", "text": filler})
                        await self.push_frame(TextFrame(text=filler), FrameDirection.DOWNSTREAM)

        elif isinstance(frame, TranscriptionFrame):
            self.turn_start_time = None

        await self.push_frame(frame, direction)
