import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.nvidia.stt import NvidiaSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.local.audio import LocalAudioTransport
from pipecat.workers.runner import WorkerRunner

from pipeline.processors import (
    InterpreterProcessor,
    InterruptWatcherProcessor,
    RendererProcessor,
)
from pipeline.turn_merger import TurnMerger
from pipeline.turns import DEFAULT_HOLD_S, build_turn_processor
from state_engine.config import PersonaConfig


async def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)

    transport = LocalAudioTransport(TransportParams(audio_in_enabled=True, audio_out_enabled=True))

    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer())
    stt = NvidiaSTTService(api_key=os.environ["NVIDIA_API_KEY"])
    turns = build_turn_processor(
        hold_s=float(os.environ.get("USER_SPEECH_TIMEOUT", DEFAULT_HOLD_S)),
        smart=os.environ.get("TURN_STOP", "timer") == "smart",
    )
    merger = TurnMerger()

    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: interpreter.state)
    interpreter = InterpreterProcessor(persona, filler_getter=lambda: interrupt_watcher.filler_line_this_turn)
    renderer = RendererProcessor(persona)
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        voice_id=os.environ["ELEVENLABS_VOICE_ID"],
    )

    pipeline = Pipeline([
        transport.input(),
        vad,
        stt,
        turns,
        merger,
        interrupt_watcher,
        interpreter,
        renderer,
        tts,
        transport.output(),
    ])

    worker = PipelineWorker(pipeline)
    runner = WorkerRunner()
    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1]))