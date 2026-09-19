import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.services.nvidia.stt import NvidiaSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.local.audio import LocalAudioTransport
from pipecat.workers.runner import WorkerRunner

from pipeline.processors import InterruptWatcherProcessor
from state_engine.config import PersonaConfig
from state_engine.engine import build_initial_state


async def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)
    fake_state = build_initial_state(persona)

    transport = LocalAudioTransport(TransportParams(audio_in_enabled=True, audio_out_enabled=False))

    stt = NvidiaSTTService(
        api_key=os.environ["NVIDIA_API_KEY"],
        model_function_map={
            "function_id": "d3fe9151-442b-4204-a70d-5fcc597fd610",
            "model_name": "parakeet-tdt-0.6b-v2",
        },
    )

    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: fake_state)

    pipeline = Pipeline([transport.input(), stt, interrupt_watcher])

    worker = PipelineWorker(pipeline)
    runner = WorkerRunner()
    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1]))