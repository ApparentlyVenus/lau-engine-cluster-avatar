import asyncio

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.local.audio import LocalAudioTransport
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from state_engine.config import PersonaConfig
from pipeline.processors import InterpreterProcessor, RendererProcessor, InterruptWatcherProcessor


async def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)

    transport = LocalAudioTransport(TransportParams(audio_in_enabled=True, audio_out_enabled=True))

    interpreter = InterpreterProcessor(persona)
    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: interpreter.state)
    renderer = RendererProcessor(persona)
    tts = ElevenLabsTTSService(api_key="ELEVENLABS_API_KEY_HERE", voice_id="VOICE_ID_HERE")

    pipeline = Pipeline([
        transport.input(),
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