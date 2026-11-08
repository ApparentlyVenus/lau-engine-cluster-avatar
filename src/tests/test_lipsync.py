"""Word timings for the 3D patient's lip sync (pipeline/lipsync.py)."""

import asyncio

import pytest
from pipecat.frames.frames import InterruptionFrame, OutputTransportMessageUrgentFrame, TTSAudioRawFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipeline.lipsync import LipSyncTap, WordTimingFrame, watch_word_timestamps

RATE = 24000
DOWN = FrameDirection.DOWNSTREAM


def audio(samples: int, ctx: str = "a") -> TTSAudioRawFrame:
    return TTSAudioRawFrame(b"\0\0" * samples, RATE, 1, context_id=ctx)


def run_tap(frames):
    """Feeds frames through a LipSyncTap and returns the word events it sent."""
    tap = LipSyncTap()
    out = []

    async def capture(frame, direction=DOWN):
        out.append(frame)

    tap.push_frame = capture

    async def noop(self, frame, direction):
        return None

    original = FrameProcessor.process_frame
    FrameProcessor.process_frame = noop  # the base needs a started pipeline
    try:
        async def go():
            for f in frames:
                await tap.process_frame(f, DOWN)
        asyncio.run(go())
    finally:
        FrameProcessor.process_frame = original
    words = [f.message for f in out if isinstance(f, OutputTransportMessageUrgentFrame)]
    passed = [f for f in out if not isinstance(f, OutputTransportMessageUrgentFrame)]
    return words, passed


def test_words_get_their_position_in_the_audio():
    words, passed = run_tap([
        audio(4800),
        WordTimingFrame(word="Is", seconds=0.0, context_id="a"),
        WordTimingFrame(word="it", seconds=0.1, context_id="a"),
        audio(4800),
        WordTimingFrame(word="serious?", seconds=0.25, context_id="a"),
        TTSStoppedFrame(context_id="a"),
    ])
    assert [(w["w"], w["s"], w["d"]) for w in words] == [
        ("Is", 0, 2400),
        ("it", 2400, 3600),
        ("serious?", 6000, round(min(0.6, 8 * 0.07) * RATE)),
    ]
    assert not any(isinstance(f, WordTimingFrame) for f in passed)  # internal frames stop here
    assert sum(isinstance(f, TTSAudioRawFrame) for f in passed) == 2


def test_second_reply_starts_where_the_first_audio_ended():
    words, _ = run_tap([
        audio(12000, "a"),
        WordTimingFrame(word="Okay.", seconds=0.0, context_id="a"),
        TTSStoppedFrame(context_id="a"),
        audio(2400, "b"),
        WordTimingFrame(word="Why?", seconds=0.05, context_id="b"),
        TTSStoppedFrame(context_id="b"),
    ])
    assert [w["s"] for w in words] == [0, 12000 + 1200]


def test_word_before_its_audio_waits_for_it():
    words, _ = run_tap([
        audio(2400, "a"),
        WordTimingFrame(word="Hello.", seconds=0.0, context_id="b"),  # b's audio not here yet
        audio(2400, "b"),
        TTSStoppedFrame(context_id="b"),
    ])
    assert [(w["w"], w["s"]) for w in words] == [("Hello.", 2400)]


def test_interruption_restarts_the_count():
    words, passed = run_tap([
        audio(9600, "a"),
        WordTimingFrame(word="Lost", seconds=0.0, context_id="a"),
        InterruptionFrame(),
        audio(2400, "b"),
        WordTimingFrame(word="Sorry.", seconds=0.0, context_id="b"),
        TTSStoppedFrame(context_id="b"),
    ])
    assert [(w["w"], w["s"]) for w in words] == [("Sorry.", 0)]  # the cut-off word is dropped
    assert any(isinstance(f, InterruptionFrame) for f in passed)


def test_long_gap_is_a_pause_not_a_long_word():
    words, _ = run_tap([
        audio(72000),
        WordTimingFrame(word="Well...", seconds=0.0, context_id="a"),
        WordTimingFrame(word="no.", seconds=2.5, context_id="a"),
        TTSStoppedFrame(context_id="a"),
    ])
    assert words[0]["d"] < RATE  # not 2.5 s of mouth movement


class FakeTTS:
    def __init__(self):
        self._initial_word_timestamp = -1
        self.pushed, self.added = [], []

    async def push_frame(self, frame, direction=DOWN):
        self.pushed.append(frame)

    async def _add_word_timestamps(self, word_times, context_id=None, includes_inter_frame_spaces=False):
        self.added.append(word_times)


def test_watch_word_timestamps_skips_cached_words():
    tts = FakeTTS()
    assert watch_word_timestamps(tts)

    async def go():
        await tts._add_word_timestamps([("early", 0.0)], "a")  # cached: no audio yet
        tts._initial_word_timestamp = 123
        await tts._add_word_timestamps([("early", 0.0), (" ", 0.1), ("words", 0.2)], "a")

    asyncio.run(go())
    assert [(f.word, f.seconds) for f in tts.pushed] == [("early", 0.0), ("words", 0.2)]
    assert len(tts.added) == 2  # the original still runs every time


def test_watch_word_timestamps_without_the_hook():
    class Bare:
        pass

    assert watch_word_timestamps(Bare()) is False


@pytest.mark.parametrize("data, ok", [
    ({"url": "/static/avatar/other.glb", "body": "M"}, True),
    ({"body": "F"}, True),
    ({"url": "model.fbx"}, False),
    ({"body": "X"}, False),
    ({"url": "a.glb", "colour": "red"}, False),
])
def test_avatar_section_is_validated(persona_dict, data, ok):
    from state_engine.validate import validate_tuning

    persona_dict["avatar"] = data
    assert (validate_tuning(persona_dict) == []) == ok
