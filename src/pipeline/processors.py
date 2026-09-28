import time

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from interpreter.claude import INTERPRETER_MODEL, call_interpreter
from interpreter.parser import parse_turn_flags
from interpreter.prompt import build_interpreter_message
from pipeline.frame import StateUpdatedFrame
from pipeline.interruption import pick_line, select_interrupt_category, should_interrupt
from renderer.claude import RENDERER_MODEL, stream_renderer
from renderer.prompt import build_renderer_message
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state
from tracing import mark, summary


class InterpreterProcessor(FrameProcessor):
    def __init__(self, persona: PersonaConfig, filler_getter=None):
        super().__init__()
        self.persona = persona
        self.state = build_initial_state(persona)
        self.history: list[str] = []
        self.filler_getter = filler_getter

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            if not frame.text.strip():
                mark("interpreter", "empty final skipped")
                return

            mark("interpreter", "final frame in", key="final")
            message = build_interpreter_message(self.persona, frame.text, self.history)
            mark("interpreter", "API call ->", f"{INTERPRETER_MODEL}, {len(message)} chars")
            raw_response = await call_interpreter(message)
            mark("interpreter", "API call <-", repr(raw_response.strip()), key="interp_done")
            flags = parse_turn_flags(raw_response)

            self.state, escalated = apply_turn(self.state, flags, self.persona)
            mark(
                "state_engine",
                "apply_turn done",
                f"trust={self.state.trust:.2f} sat={self.state.saturation:.2f} escalated={escalated}",
                key="state_done",
            )
            self.history.append(frame.text)

            filler_line = self.filler_getter() if self.filler_getter else None

            await self.push_frame(
                StateUpdatedFrame(
                    state=self.state,
                    learner_transcript=frame.text,
                    escalated=escalated,
                    filler_line=filler_line,
                ),
                direction,
            )
        else:
            await self.push_frame(frame, direction)


class RendererProcessor(FrameProcessor):
    def __init__(self, persona: PersonaConfig):
        super().__init__()
        self.persona = persona
        self.history: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StateUpdatedFrame):
            self.history.append(f"Learner: {frame.learner_transcript}")
            message = build_renderer_message(
                self.persona,
                frame.state,
                frame.learner_transcript,
                history=self.history,
                filler_line=frame.filler_line,
            )
            mark("renderer", "API call ->", f"{RENDERER_MODEL}, {len(message)} chars")

            full_line = ""
            async for chunk in stream_renderer(message):
                mark("renderer", "chunk -> TTS", repr(chunk), key="first_chunk")
                full_line += chunk + " "
                await self.push_frame(TextFrame(text=chunk), direction)

            mark("renderer", "stream done", key="render_done")
            self.history.append(f"Patient: {full_line.strip()}")
            summary()
        else:
            await self.push_frame(frame, direction)


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