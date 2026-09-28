import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

import tracing
from pipeline.processors import (
    InterpreterProcessor,
    InterruptWatcherProcessor,
    RendererProcessor,
)
from state_engine.config import PersonaConfig
from tracing import mark

logger.remove()
logger.add(sys.stderr, level="WARNING")

DEFAULT_LINES = [
    "hello miss layla, please sit down, i have your results",
    "i have difficult news, the biopsy came back and it is breast cancer",
    "i'm sorry, this must be really hard to hear",
    "don't worry, we caught it early and it will be fine",
    "we can start treatment as soon as possible",
    "are you slow? i already told you",
]

WORDS_PER_SECOND = 2.5
ENDPOINT_MS = 400
SETTLE_SECONDS = 6.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_script_lines(path: str) -> list[str]:
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


async def speak(worker, text: str):
    words = text.split()
    delay = 1.0 / WORDS_PER_SECOND
    tracing.new_turn()
    mark("fake_stt", "speech starts", repr(text))
    for i in range(1, len(words) + 1):
        await asyncio.sleep(delay)
        await worker.queue_frame(
            InterimTranscriptionFrame(text=" ".join(words[:i]), user_id="learner", timestamp=now_iso())
        )
    mark("fake_stt", "last word spoken", key="last_word")
    await asyncio.sleep(ENDPOINT_MS / 1000)
    mark("fake_stt", "final frame queued")
    await worker.queue_frame(
        TranscriptionFrame(text=text, user_id="learner", timestamp=now_iso())
    )


class PrintSink(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        is_speech = isinstance(frame, TextFrame) and not isinstance(
            frame, (TranscriptionFrame, InterimTranscriptionFrame)
        )
        if is_speech:
            mark("sink", "TTS would speak", repr(frame.text))

        await self.push_frame(frame, direction)


def print_state(state):
    print(
        f"    state: trust={state.trust:.2f} sat={state.saturation:.2f} "
        f"unack={state.unacknowledged_turns} "
        f"{state.emotion.primary.name}/{state.emotion.secondary.name} "
        f"defense={state.defense.mode.name}"
    )


async def main(persona_path: str, mode: str | None):
    persona = PersonaConfig.from_file(persona_path)

    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: interpreter.state)
    interpreter = InterpreterProcessor(persona, filler_getter=lambda: interrupt_watcher.filler_line_this_turn)
    renderer = RendererProcessor(persona)
    sink = PrintSink()

    pipeline = Pipeline([interrupt_watcher, interpreter, renderer, sink])
    worker = PipelineWorker(pipeline)
    runner = WorkerRunner()
    await runner.add_workers(worker)
    run_task = asyncio.create_task(runner.run())
    await asyncio.sleep(1.0)

    if mode == "-i":
        while True:
            text = (await asyncio.to_thread(input, "\nLearner: ")).strip()
            if text.lower() == "quit":
                break
            await speak(worker, text)
            await asyncio.sleep(SETTLE_SECONDS)
            print_state(interpreter.state)
    else:
        if mode:
            lines = await asyncio.to_thread(load_script_lines, mode)
        else:
            lines = DEFAULT_LINES
        for text in lines:
            print(f"\nLearner: {text}")
            await speak(worker, text)
            await asyncio.sleep(SETTLE_SECONDS)
            print_state(interpreter.state)

    run_task.cancel()
    await asyncio.wait({run_task}, timeout=2)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))