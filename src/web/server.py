"""Browser mic mode. Serves one page and one WebSocket.

Works inside the devcontainer: audio travels over the WebSocket (TCP), which
VSCode forwards like any other port. WebRTC would need UDP, which it does not.

Each connection is a fresh conversation with a fresh patient state.
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from pipecat.frames.frames import OutputTransportMessageUrgentFrame
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

import tracing
from pipeline.build import SessionOptions, build_session
from pipeline.processors import state_summary
from state_engine.config import PersonaConfig
from tracing import mark
from web.serializer import IN_SAMPLE_RATE, OUT_SAMPLE_RATE, PcmJsonSerializer

PAGE = Path(__file__).with_name("index.html")


def create_app(persona_path: str, opts: SessionOptions) -> FastAPI:
    app = FastAPI()
    persona = PersonaConfig.from_file(persona_path)
    active: dict[str, asyncio.Task] = {}

    @app.get("/")
    async def index():
        return HTMLResponse(PAGE.read_text())

    @app.get("/config")
    async def config():
        return {
            "patient": persona.scenario.patient_name,
            "age": persona.scenario.age,
            "barge_in": opts.barge_in,
            "tts": opts.tts,
            "in_rate": IN_SAMPLE_RATE,
            "out_rate": OUT_SAMPLE_RATE,
        }

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()

        # One conversation at a time: a new tab replaces the old session.
        for task in active.values():
            task.cancel()
        active.clear()

        session_opts = SessionOptions(**{**opts.__dict__})
        barge = websocket.query_params.get("barge_in")
        if barge is not None:
            session_opts.barge_in = barge == "1"

        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=IN_SAMPLE_RATE,
                audio_out_sample_rate=OUT_SAMPLE_RATE,
                add_wav_header=False,
                serializer=PcmJsonSerializer(),
                session_timeout=None,
            ),
        )
        session = build_session(persona_path, session_opts, transport.input(), transport.output())

        def send_latency(result: dict):
            asyncio.create_task(session.worker.queue_frame(
                OutputTransportMessageUrgentFrame(message={"type": "latency", **result})
            ))

        tracing._listeners.clear()
        tracing.on_summary(send_latency)

        @transport.event_handler("on_client_connected")
        async def on_connected(_transport, _ws):
            mark("web", "browser connected")
            await session.worker.queue_frame(OutputTransportMessageUrgentFrame(message={
                "type": "state", "flags": {}, "escalated": False,
                **state_summary(persona, session.interpreter.state),
            }))

        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(_transport, _ws):
            mark("web", "browser disconnected")
            await session.worker.cancel()

        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(session.worker)
        task = asyncio.create_task(runner.run())
        active["session"] = task
        try:
            await task
        except asyncio.CancelledError:
            await session.worker.cancel()

    return app


def serve(persona_path: str, opts: SessionOptions, host: str, port: int):
    import uvicorn

    print(f"\n  Open http://localhost:{port} in your browser (VSCode forwards the port).")
    print("  Use headphones: without them her voice can leak into the mic and trigger barge-in.\n")
    uvicorn.run(create_app(persona_path, opts), host=host, port=port, log_level="warning")

