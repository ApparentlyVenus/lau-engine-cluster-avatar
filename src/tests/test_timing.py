import asyncio
from types import SimpleNamespace

import pytest

from interpreter.prompt import build_interpreter_message
from pipeline.timing import (
    LiveTiming,
    TimingConfig,
    TurnTiming,
    Word,
    annotate_transcript,
    timing_block,
    words_from_riva_result,
)
from pipeline.tts import strip_tags

CFG = TimingConfig()


def words(*items):
    return [Word(w, s, e) for w, s, e in items]


SORRY = words(
    ("I'm", 0.0, 0.2), ("sorry", 0.25, 0.6),
    # 1.8 s pause
    ("this", 2.4, 2.55), ("must", 2.6, 2.8), ("be", 2.85, 2.95),
    ("really", 3.0, 3.3), ("hard", 3.35, 3.6),
)


# --- Riva extraction -------------------------------------------------------

def test_words_from_riva_result_converts_ms():
    w = SimpleNamespace(word="hello", start_time=1200, end_time=1500)
    result = SimpleNamespace(alternatives=[SimpleNamespace(words=[w])])
    assert words_from_riva_result(result) == [Word("hello", 1.2, 1.5)]


def test_words_from_riva_result_handles_missing():
    assert words_from_riva_result(None) == []
    assert words_from_riva_result(SimpleNamespace(alternatives=[])) == []
    assert words_from_riva_result(SimpleNamespace(alternatives=[SimpleNamespace(words=[])])) == []


def test_real_riva_proto_shape():
    riva = pytest.importorskip("riva.client.proto.riva_asr_pb2")
    r = riva.StreamingRecognitionResult()
    alt = r.alternatives.add()
    w = alt.words.add()
    w.word, w.start_time, w.end_time = "okay", 500, 800
    assert words_from_riva_result(r) == [Word("okay", 0.5, 0.8)]


# --- pauses and annotation ---------------------------------------------------

def test_pause_detected_and_annotated():
    t = TurnTiming(words=SORRY)
    assert [(i, round(g, 2)) for i, g in t.pauses(CFG)] == [(1, 1.8)]
    assert annotate_transcript("x", t, CFG) == "I'm sorry [pause 1.8s] this must be really hard"


def test_short_gaps_are_not_pauses():
    t = TurnTiming(words=words(("a", 0, 0.2), ("b", 0.6, 0.8)))
    assert t.pauses(CFG) == []


def test_negative_gap_from_stream_restart_is_ignored():
    t = TurnTiming(words=words(("a", 50.0, 50.2), ("b", 0.1, 0.3)))
    assert t.pauses(CFG) == []


def test_no_words_falls_back_to_transcript():
    assert annotate_transcript("Hello there.", TurnTiming(), CFG) == "Hello there."


def test_rate_excludes_pauses_and_fillers():
    t = TurnTiming(words=SORRY)
    # 7 words over 3.6 s minus the 1.8 s pause = 1.8 s -> ~233 wpm
    assert 220 < t.speaking_rate_wpm(CFG) < 245


def test_rate_needs_enough_words():
    assert TurnTiming(words=words(("hi", 0, 0.3))).speaking_rate_wpm(CFG) is None


def test_fillers_counted():
    t = TurnTiming(words=words(("um", 0, 0.2), ("the", 0.3, 0.4), ("uh", 0.5, 0.7), ("scan", 0.8, 1.0)))
    assert t.filler_count() == 2


# --- measured block ----------------------------------------------------------

def test_block_reports_gap_pause_and_rate():
    t = TurnTiming(words=SORRY, live=LiveTiming(gap_after_her_line_s=2.4))
    block = timing_block(t, CFG)
    assert "Started speaking 2.4s after she finished." in block
    assert 'Longest pause: 1.8s, after "sorry".' in block
    assert "(fast)" in block


def test_block_reports_talk_over_instead_of_gap():
    t = TurnTiming(live=LiveTiming(gap_after_her_line_s=1.0, talked_over_her=True))
    assert timing_block(t, CFG) == "- Started speaking while she was still talking."


def test_block_is_none_when_nothing_measured():
    assert timing_block(TurnTiming(), CFG) is None


def test_interpreter_message_includes_timing(persona):
    msg = build_interpreter_message(persona, "I'm sorry [pause 1.8s] this is hard", [], timing="- Longest pause: 1.8s.")
    assert "[pause 1.8s]" in msg
    assert "Measured timing:\n- Longest pause: 1.8s." in msg
    plain = build_interpreter_message(persona, "Hello.", [])
    assert "Measured timing" not in plain


def test_timing_config_from_tuning(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('{"timing": {"pause_threshold_s": 1.2}}')
    assert TimingConfig.from_tuning_file(str(p)).pause_threshold_s == 1.2
    p.write_text("{}")
    assert TimingConfig.from_tuning_file(str(p)) == TimingConfig()
    p.write_text('{"timing": {"typo": 1}}')
    with pytest.raises(ValueError):
        TimingConfig.from_tuning_file(str(p))


def test_shipped_tuning_file_timing_section_loads():
    from pathlib import Path
    path = Path(__file__).parents[1] / "state_engine" / "tuning" / "tuning.json"
    assert TimingConfig.from_tuning_file(str(path)).pause_threshold_s > 0


# --- tag stripping for Flash ------------------------------------------------

def test_strip_tags():
    assert strip_tags("[shocked] Wait, what? [pause] No.") == "Wait, what?... No."
    assert strip_tags("[voice breaking] I just [quietly] can't.") == "I just can't."
    assert strip_tags("[pause]") == "..."
    assert strip_tags("[pause] [pause] Okay.") == "... Okay."


# --- merger keeps word timings ----------------------------------------------

def test_merger_carries_words_from_all_fragments():
    from datetime import datetime, timezone

    from pipecat.frames.frames import TranscriptionFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    from pipeline.turn_merger import TurnMerger

    def riva(*ws):
        return SimpleNamespace(alternatives=[SimpleNamespace(
            words=[SimpleNamespace(word=w, start_time=s, end_time=e) for w, s, e in ws])])

    merger = TurnMerger()
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    merger.push_frame = capture

    async def run():
        ts = datetime.now(timezone.utc).isoformat()
        down = FrameDirection.DOWNSTREAM
        await merger.process_frame(UserStartedSpeakingFrame(), down)
        await merger.process_frame(TranscriptionFrame("I'm sorry", "u", ts, result=riva(("I'm", 0, 200), ("sorry", 250, 600))), down)
        await merger.process_frame(TranscriptionFrame("to hear", "u", ts, result=riva(("to", 2400, 2500), ("hear", 2550, 2800))), down)
        await merger.process_frame(UserStoppedSpeakingFrame(), down)

    # process_frame on the base class needs a started processor; bypass it.
    from pipecat.processors.frame_processor import FrameProcessor

    async def noop(self, frame, direction):
        return None

    original = FrameProcessor.process_frame
    FrameProcessor.process_frame = noop
    try:
        asyncio.run(run())
    finally:
        FrameProcessor.process_frame = original

    final = [f for f in pushed if isinstance(f, TranscriptionFrame)][-1]
    assert final.text == "I'm sorry to hear"
    assert isinstance(final.result, TurnTiming)
    assert [w.word for w in final.result.words] == ["I'm", "sorry", "to", "hear"]
    assert annotate_transcript(final.text, final.result, CFG) == "I'm sorry [pause 1.8s] to hear"
