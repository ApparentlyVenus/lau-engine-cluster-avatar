import time

from interruption import pick_line, select_interrupt_category, should_interrupt
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
from renderer.claude import call_renderer
from renderer.prompt import build_renderer_message
from state_engine.config import PersonaConfig
from state_engine.engine import apply_turn, build_initial_state


class InterpreterProcessor(FrameProcessor):
    def __init__(self, persona: PersonaConfig):
        super().__init__()
        self.persona = persona
        self.state = build_initial_state(persona)
        self.history: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            message = build_interpreter_message(self.persona, frame.text, self.history)
            raw_response = await call_interpreter(message)
            flags = parse_turn_flags(raw_response)

            self.state, escalated = apply_turn(self.state, flags, self.persona)
            self.history.append(frame.text)

            await self.push_frame(StateUpdatedFrame(state=self.state, learner_transcript=frame.text, escalated=escalated), direction)
        else:
            await self.push_frame(frame, direction)


class RendererProcessor(FrameProcessor):
    def __init__(self, persona: PersonaConfig):
        super().__init__()
        self.persona = persona

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StateUpdatedFrame):
            message = build_renderer_message(self.persona, frame.state, frame.learner_transcript)
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

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            if self.turn_start_time is None:
                self.turn_start_time = time.monotonic()

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
                        await self.push_frame(TextFrame(text=filler), FrameDirection.DOWNSTREAM)

        elif isinstance(frame, TranscriptionFrame):
            self.turn_start_time = None
            self.interrupted_this_turn = False

        await self.push_frame(frame, direction)