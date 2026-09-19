import time

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from interpreter.claude import call_interpreter
from interpreter.parser import parse_turn_flags
from interpreter.prompt import build_interpreter_message
from pipeline.frame import StateUpdatedFrame
from pipeline.interruption import pick_line, select_interrupt_category, should_interrupt
from renderer.claude import call_renderer
from renderer.prompt import build_renderer_message
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state


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
            message = build_interpreter_message(self.persona, frame.text, self.history)
            raw_response = await call_interpreter(message)
            flags = parse_turn_flags(raw_response)

            self.state, escalated = apply_turn(self.state, flags, self.persona)
            self.history.append(frame.text)

            filler_line = self.filler_getter() if self.filler_getter else None

            await self.push_frame(
                StateUpdatedFrame(state=self.state, learner_transcript=frame.text, escalated=escalated, filler_line=filler_line),
                direction,
            )
        else:
            await self.push_frame(frame, direction)


class RendererProcessor(FrameProcessor):
    def __init__(self, persona: PersonaConfig):
        super().__init__()
        self.persona = persona

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StateUpdatedFrame):
            message = build_renderer_message(self.persona, frame.state, frame.learner_transcript, filler_line=frame.filler_line)
            line = await call_renderer(message)
            await self.push_frame(TextFrame(text=line), direction)
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
                        await self.push_frame(TextFrame(text=filler), FrameDirection.DOWNSTREAM)

        elif isinstance(frame, TranscriptionFrame):
            self.turn_start_time = None

        await self.push_frame(frame, direction)