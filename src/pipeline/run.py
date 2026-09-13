import asyncio
import os

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.nvidia.stt import NvidiaSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.local.audio import LocalAudioTransport

from pipeline.processors import (
    InterpreterProcessor,
    InterruptWatcherProcessor,
    RendererProcessor,
)
from state_engine.config import PersonaConfig


async def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)

    transport = LocalAudioTransport(TransportParams(audio_in_enabled=True, audio_out_enabled=True))

    stt = NvidiaSTTService(api_key=os.environ["NVIDIA_API_KEY"])

    interpreter = InterpreterProcessor(persona)
    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: interpreter.state)
    renderer = RendererProcessor(persona)
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        voice_id=os.environ["ELEVENLABS_VOICE_ID"],
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        interrupt_watcher,
        interpreter,
        renderer,
        tts,
        transport.output(),
    ])

    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    await runner.run(task)


if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1]))