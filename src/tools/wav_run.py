"""Feed recorded clips through the full pipeline and log every stage.

Preferred:  python src/run.py wav clips/a.wav clips/b.wav          (with voice, saves her replies)
            python src/run.py wav clips/a.wav --no-tts             (text only)
Old form, still works (text only):
            python -m tools.wav_run tuning.json clips/a.wav --hold=0.6 --smart
"""

import asyncio
import os
import sys
import time
import wave
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    StartFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

import tracing
from pipeline.build import SessionOptions, build_session
from pipeline.timing import words_from_riva_result
from tracing import mark

SAMPLE_RATE = 16000
OUT_RATE = 24000
CHUNK_S = 0.1
TAIL_SILENCE_S = 4.0
SETTLE_S = 9.0


def load_clip(path: str) -> bytes:
    with wave.open(path, "rb") as wf:
        if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16 kHz, mono, 16-bit")
        return wf.readframes(wf.getnframes())


class EventProbe(FrameProcessor):
    def __init__(self, label: str, kinds: tuple[type, ...], show_first_interim: bool = False):
        super().__init__()
        self.label = label
        self.kinds = kinds
        self.show_first_interim = show_first_interim
        self.interim_seen = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            if self.show_first_interim and not self.interim_seen:
                self.interim_seen = True
                mark(self.label, "first interim", repr(frame.text))
        elif isinstance(frame, TranscriptionFrame) and TranscriptionFrame in self.kinds:
            self.interim_seen = False
            words = words_from_riva_result(frame.result)
            detail = repr(frame.text)
            if words:
                detail += "  words: " + " ".join(f"{w.word}@{w.start_s:.2f}-{w.end_s:.2f}" for w in words)
            mark(self.label, "FINAL", detail)
        elif isinstance(frame, self.kinds) and not isinstance(frame, TranscriptionFrame):
            if isinstance(frame, VADUserStoppedSpeakingFrame):
                mark(self.label, type(frame).__name__, key="last_word", overwrite=True)
            else:
                mark(self.label, type(frame).__name__)

        await self.push_frame(frame, direction)


class Sink(FrameProcessor):
    """End of the pipeline in file mode: logs her text, collects her audio."""

    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.audio = bytearray()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self.started.set()
        elif isinstance(frame, TTSAudioRawFrame):
            if not self.audio:
                tracing.audio_started()
            self.audio.extend(frame.audio)
        elif type(frame) is TextFrame:
            mark("sink", "to TTS", repr(frame.text))

        await self.push_frame(frame, direction)

    def take_audio(self) -> bytes:
        audio, self.audio = bytes(self.audio), bytearray()
        return audio


async def feed_clip(worker, pcm: bytes):
    chunk_bytes = int(SAMPLE_RATE * CHUNK_S) * 2
    padded = pcm + bytes(int(SAMPLE_RATE * TAIL_SILENCE_S) * 2)
    tracing.new_turn()
    mark("feeder", "audio starts", f"{len(pcm) / 2 / SAMPLE_RATE:.2f}s of audio")
    start = time.monotonic()
    marked_end = False
    for n, offset in enumerate(range(0, len(padded), chunk_bytes)):
        await asyncio.sleep(max(0.0, start + (n + 1) * CHUNK_S - time.monotonic()))
        if not marked_end and offset >= len(pcm):
            mark("feeder", "audio ends")
            marked_end = True
        await worker.queue_frame(
            InputAudioRawFrame(audio=padded[offset:offset + chunk_bytes], sample_rate=SAMPLE_RATE, num_channels=1)
        )


def print_state(state):
    print(
        f"    state: trust={state.trust:.2f} sat={state.saturation:.2f} "
        f"unack={state.unacknowledged_turns} "
        f"{state.emotion.primary.name}/{state.emotion.secondary.name} "
        f"defense={state.defense.mode.name}"
    )


def save_wav(path: Path, pcm: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(OUT_RATE)
        wf.writeframes(pcm)


async def run_clips(persona_path: str, clips: list[str], opts: SessionOptions, out_dir: str = "out"):
    sink = Sink()
    probes = {
        "vad": [EventProbe("vad", (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame))],
        "stt": [EventProbe("stt", (TranscriptionFrame,), show_first_interim=True)],
        "turns": [EventProbe("turn", (UserStartedSpeakingFrame, UserStoppedSpeakingFrame))],
        "output": [sink],
    }
    session = build_session(persona_path, opts, probes=probes)
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(session.worker)
    run_task = asyncio.create_task(runner.run())
    await sink.started.wait()
    await asyncio.sleep(0.5)

    print(f"turn end: {'smart turn model' if opts.smart_turn else f'timer, hold {opts.hold_s}s'}")
    for path in clips:
        print(f"\n=== {path}")
        await feed_clip(session.worker, load_clip(path))
        await asyncio.sleep(SETTLE_S)
        print_state(session.interpreter.state)
        audio = sink.take_audio()
        if audio:
            out = Path(out_dir) / f"{Path(path).stem}_reply.wav"
            save_wav(out, audio)
            print(f"    her reply: {out} ({len(audio) / 2 / OUT_RATE:.1f}s)")

    run_task.cancel()
    await asyncio.wait({run_task}, timeout=2)
    sys.stdout.flush()
    os._exit(0)


def parse_args(argv: list[str]):
    opts = SessionOptions(tts=False, barge_in=False)
    positional = []
    for arg in argv:
        if arg.startswith("--hold="):
            opts.hold_s = float(arg.split("=", 1)[1])
        elif arg == "--smart":
            opts.smart_turn = True
        else:
            positional.append(arg)
    return positional[0], positional[1:], opts


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    persona_path, clips, opts = parse_args(sys.argv[1:])
    asyncio.run(run_clips(persona_path, clips, opts))
