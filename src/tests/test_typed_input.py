"""Typed turns (pipeline/typed_input.py and the serializer's "say" message)."""

import asyncio
import json

from pipecat.frames.frames import (
    InputTransportMessageFrame,
    InterruptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipeline.turn_gate import TurnGate
from pipeline.turn_merger import TurnMerger
from pipeline.typed_input import TypedTurnInput
from web.serializer import PcmJsonSerializer

DOWN = FrameDirection.DOWNSTREAM


def run(coro):
    async def noop(self, frame, direction):
        return None

    original = FrameProcessor.process_frame
    FrameProcessor.process_frame = noop  # the base needs a started pipeline
    try:
        return asyncio.run(coro)
    finally:
        FrameProcessor.process_frame = original


def test_serializer_reads_a_typed_turn():
    s = PcmJsonSerializer()
    frame = asyncio.run(s.deserialize(json.dumps({"type": "say", "text": "Please take a seat."})))
    assert isinstance(frame, InputTransportMessageFrame)
    assert frame.message == {"type": "say", "text": "Please take a seat."}
    assert asyncio.run(s.deserialize("not json")) is None
    assert asyncio.run(s.deserialize(json.dumps({"type": "other"}))) is None


def test_typed_turn_reaches_the_interpreter_like_speech():
    gate = TurnGate()
    typed = TypedTurnInput(gate=gate)
    merger = TurnMerger(gate=gate)
    out = []

    async def to_merger(frame, direction=DOWN):
        await merger.process_frame(frame, direction)

    async def capture(frame, direction=DOWN):
        out.append(frame)

    typed.push_frame = to_merger
    merger.push_frame = capture

    async def go():
        await typed.process_frame(InputTransportMessageFrame(message={"type": "say", "text": "  I have your results.  "}), DOWN)

    run(go())
    finals = [f for f in out if isinstance(f, TranscriptionFrame)]
    assert [f.text for f in finals] == ["I have your results."]
    assert finals[0].result.words == []  # no timing for typed turns
    assert gate.pending is not None and gate.pending.text == "I have your results."
    assert any(isinstance(f, UserStartedSpeakingFrame) for f in out)
    assert any(isinstance(f, UserStoppedSpeakingFrame) for f in out)


def test_empty_typed_turn_is_ignored_and_other_messages_pass():
    typed = TypedTurnInput()
    out = []

    async def capture(frame, direction=DOWN):
        out.append(frame)

    typed.push_frame = capture
    other = InputTransportMessageFrame(message={"type": "ping"})

    async def go():
        await typed.process_frame(InputTransportMessageFrame(message={"type": "say", "text": "   "}), DOWN)
        await typed.process_frame(other, DOWN)

    run(go())
    assert out == [other]


def test_typing_over_her_interrupts_only_with_barge_in():
    class Tracker:
        bot_speaking = True

    for barge_in, expected in ((True, 1), (False, 0)):
        typed = TypedTurnInput(timing_tracker=Tracker(), barge_in=barge_in)
        calls = []

        async def interrupt():
            calls.append(InterruptionFrame())

        async def capture(frame, direction=DOWN):
            pass

        typed.broadcast_interruption = interrupt
        typed.push_frame = capture

        async def go():
            await typed.process_frame(InputTransportMessageFrame(message={"type": "say", "text": "Sorry, go on."}), DOWN)

        run(go())
        assert len(calls) == expected
