import asyncio
import os
import time

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from interpreter.claude import INTERPRETER_MODEL, call_interpreter
from interpreter.parser import parse_turn_flags
from interpreter.prompt import build_interpreter_message
import llm_client
from pipeline.frame import StateUpdatedFrame, TurnStartedFrame
from pipeline.interruption import pick_line, select_interrupt_category, should_interrupt
from renderer.claude import RENDERER_MODEL, stream_renderer
from renderer.prompt import build_renderer_message
from renderer.speculation import speculative_render
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state
from state_engine.turn_flags import TurnFlags
from tracing import mark, summary

SPECULATIVE_RENDER = os.environ.get("SPECULATIVE_RENDER", "1") != "0"


class InterpreterProcessor(FrameProcessor):
    def __init__(self, persona: PersonaConfig, filler_getter=None):
        super().__init__()
        self.persona = persona
        self.state = build_initial_state(persona)
        self.history: list[str] = []
        self.filler_getter = filler_getter
        self.turn_id = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (UserStartedSpeakingFrame, InterimTranscriptionFrame)):
            # Re-open the API connection while the learner is still talking.
            llm_client.warm()

        if isinstance(frame, TranscriptionFrame):
            if not frame.text.strip():
                mark("interpreter", "empty final skipped")
                return

            self.turn_id += 1
            turn_id = self.turn_id
            mark("interpreter", "final frame in", key="final")

            # Built before this turn's line is added, as before.
            message = build_interpreter_message(self.persona, frame.text, self.history)
            self.history.append(f"Learner: {frame.text}")
            filler_line = self.filler_getter() if self.filler_getter else None

            # Let the renderer start now on the no-flags prediction.
            predicted_state, _ = apply_turn(self.state, TurnFlags(), self.persona)
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

            mark("interpreter", "API call ->", f"{INTERPRETER_MODEL}, {len(message)} chars")
            try:
                raw_response = await call_interpreter(message)
                mark("interpreter", "API call <-", repr(raw_response.strip()), key="interp_done")
                flags = parse_turn_flags(raw_response)
            except Exception as e:
                # Degrade quietly live: treat the turn as flagless rather than
                # dropping it. This is loud in the log on purpose.
                mark("interpreter", "FAILED, no flags", repr(e), key="interp_done")
                flags = TurnFlags()

            self.state, escalated = apply_turn(self.state, flags, self.persona)
            mark(
                "state_engine",
                "apply_turn done",
                f"trust={self.state.trust:.2f} sat={self.state.saturation:.2f} escalated={escalated}",
                key="state_done",
            )

            await self.push_frame(
                StateUpdatedFrame(
                    state=self.state,
                    learner_transcript=frame.text,
                    escalated=escalated,
                    filler_line=filler_line,
                    history=self.history,
                    turn_id=turn_id,
                ),
                direction,
            )
        else:
            await self.push_frame(frame, direction)


class RendererProcessor(FrameProcessor):
    """Renders her line. Work runs in background tasks so this processor never
    blocks on an API call, and turns are rendered strictly one after another."""

    def __init__(self, persona: PersonaConfig, speculative: bool = SPECULATIVE_RENDER):
        super().__init__()
        self.persona = persona
        self.speculative = speculative
        self.pending: dict[int, asyncio.Future] = {}
        self.last_task: asyncio.Task | None = None
        self.hits = 0
        self.misses = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TurnStartedFrame):
            if self.speculative:
                future = asyncio.get_running_loop().create_future()
                self.pending[frame.turn_id] = future
                self._chain(self._render_speculative(frame, future, direction))

        elif isinstance(frame, StateUpdatedFrame):
            future = self.pending.pop(frame.turn_id, None) if frame.turn_id is not None else None
            if future is not None:
                if not future.done():
                    future.set_result(frame)
            else:
                self._chain(self._render_direct(frame, direction))

        else:
            await self.push_frame(frame, direction)

    def _chain(self, coro):
        previous = self.last_task

        async def run():
            if previous is not None:
                try:
                    await previous
                except BaseException:
                    pass
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as e:
                mark("renderer", "FAILED", repr(e))

        self.last_task = asyncio.create_task(run())

    def _message(self, state, transcript, history, filler_line) -> str:
        return build_renderer_message(
            self.persona, state, transcript, history=history, filler_line=filler_line
        )

    async def _emit(self, chunk: str, direction: FrameDirection):
        mark("renderer", "chunk -> TTS", repr(chunk), key="first_chunk")
        await self.push_frame(TextFrame(text=chunk), direction)

    async def _render_speculative(self, frame: TurnStartedFrame, future: asyncio.Future, direction):
        history = frame.history if frame.history is not None else []
        snapshot = list(history)
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
        mark("renderer", "stream done", f"speculation {'HIT' if hit else 'MISS'} ({self.hits} hit / {self.misses} miss)", key="render_done")
        history.append(f"Patient: {line.strip()}")
        summary()

    async def _render_direct(self, frame: StateUpdatedFrame, direction):
        history = frame.history if frame.history is not None else []
        message = self._message(frame.state, frame.learner_transcript, history, frame.filler_line)
        mark("renderer", "API call ->", f"{RENDERER_MODEL}, {len(message)} chars")

        full_line = ""
        async for chunk in stream_renderer(message):
            await self._emit(chunk, direction)
            full_line += chunk + " "

        mark("renderer", "stream done", key="render_done")
        history.append(f"Patient: {full_line.strip()}")
        summary()

    async def cleanup(self):
        await super().cleanup()
        if self.last_task is not None and not self.last_task.done():
            self.last_task.cancel()
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
                        await self.push_frame(TextFrame(text=filler), FrameDirection.DOWNSTREAM)

        elif isinstance(frame, TranscriptionFrame):
            self.turn_start_time = None

        await self.push_frame(frame, direction)