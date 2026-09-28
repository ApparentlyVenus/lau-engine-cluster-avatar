import asyncio
import os
import sys
import time
import wave

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    StartFrame,
    TextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.nvidia.stt import NvidiaSTTService
from pipecat.workers.runner import WorkerRunner

import tracing
from pipeline.processors import (
    InterpreterProcessor,
    InterruptWatcherProcessor,
    RendererProcessor,
)
from pipeline.turn_merger import TurnMerger
from pipeline.turns import DEFAULT_HOLD_S, build_turn_processor
from state_engine.config import PersonaConfig
from tracing import mark

logger.remove()
logger.add(sys.stderr, level="WARNING")

SAMPLE_RATE = 16000
CHUNK_S = 0.1
TAIL_SILENCE_S = 4.0
SETTLE_S = 9.0

STARTED = asyncio.Event()


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
            mark(self.label, "FINAL", repr(frame.text))
        elif isinstance(frame, self.kinds) and not isinstance(frame, TranscriptionFrame):
            if isinstance(frame, VADUserStoppedSpeakingFrame):
                mark(self.label, type(frame).__name__, key="last_word", overwrite=True)
            else:
                mark(self.label, type(frame).__name__)

        await self.push_frame(frame, direction)


class PrintSink(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            STARTED.set()

        is_speech = isinstance(frame, TextFrame) and not isinstance(
            frame, (TranscriptionFrame, InterimTranscriptionFrame)
        )
        if is_speech:
            mark("sink", "TTS would speak", repr(frame.text))

        await self.push_frame(frame, direction)


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
            InputAudioRawFrame(
                audio=padded[offset:offset + chunk_bytes],
                sample_rate=SAMPLE_RATE,
                num_channels=1,
            )
        )


def print_state(state):
    print(
        f"    state: trust={state.trust:.2f} sat={state.saturation:.2f} "
        f"unack={state.unacknowledged_turns} "
        f"{state.emotion.primary.name}/{state.emotion.secondary.name} "
        f"defense={state.defense.mode.name}"
    )


def parse_args(argv: list[str]):
    hold = DEFAULT_HOLD_S
    smart = False
    positional = []
    for arg in argv:
        if arg.startswith("--hold="):
            hold = float(arg.split("=", 1)[1])
        elif arg == "--smart":
            smart = True
        else:
            positional.append(arg)
    return positional[0], positional[1:], hold, smart


async def main(persona_path: str, clips: list[str], hold: float, smart: bool):
    persona = PersonaConfig.from_file(persona_path)

    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer())
    stt = NvidiaSTTService(api_key=os.environ["NVIDIA_API_KEY"])
    turns = build_turn_processor(hold_s=hold, smart=smart)
    merger = TurnMerger(on_event=lambda event, detail="": mark("merger", event, detail))

    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: interpreter.state)
    interpreter = InterpreterProcessor(persona, filler_getter=lambda: interrupt_watcher.filler_line_this_turn)
    renderer = RendererProcessor(persona)

    pipeline = Pipeline([
        vad,
        EventProbe("vad", (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)),
        stt,
        EventProbe("stt", (TranscriptionFrame,), show_first_interim=True),
        turns,
        EventProbe("turn", (UserStartedSpeakingFrame, UserStoppedSpeakingFrame)),
        merger,
        interrupt_watcher,
        interpreter,
        renderer,
        PrintSink(),
    ])
    worker = PipelineWorker(pipeline)
    runner = WorkerRunner()
    await runner.add_workers(worker)
    run_task = asyncio.create_task(runner.run())
    await STARTED.wait()
    await asyncio.sleep(0.5)

    print(f"turn end: {'smart turn model' if smart else f'timer, hold {hold}s'}")
    for path in clips:
        print(f"\n=== {path}")
        await feed_clip(worker, load_clip(path))
        await asyncio.sleep(SETTLE_S)
        print_state(interpreter.state)

    run_task.cancel()
    await asyncio.wait({run_task}, timeout=2)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    persona_path, clips, hold, smart = parse_args(sys.argv[1:])
    asyncio.run(main(persona_path, clips, hold, smart))