"""The web app: talk to a patient, and create or edit patients.

    /                       the app (static/index.html)
    /ws?character=ID        one live session with that character
    /api/characters...      list, read, save, create, delete characters
    /api/validate           check a character without saving it
    /api/voice-test         speak a sample line in a voice (ElevenLabs HTTP)
    /login, /logout         the single shared login (web/auth.py), when APP_USERNAME/APP_PASSWORD are set

Works inside the devcontainer: audio travels over the WebSocket (TCP), which
VSCode forwards like any other port. WebRTC would need UDP, which it does not.

Each connection is a fresh conversation with a fresh patient state, loaded
from the character file when the session starts.
"""

import asyncio
import os
import time
from pathlib import Path

import httpx
from urllib.parse import parse_qs

from fastapi import Body, FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pipecat.frames.frames import OutputTransportMessageUrgentFrame
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

import tracing
from pipeline.build import SessionOptions, build_session
from pipeline.processors import state_summary
from state_engine.config import PersonaConfig
from state_engine.config import tuning_defaults
from state_engine.validate import validate_tuning
from tracing import mark
from web import auth
from web.characters import CharacterError, CharacterStore, warnings_for
from web.serializer import IN_SAMPLE_RATE, OUT_SAMPLE_RATE, PcmJsonSerializer

STATIC = Path(__file__).with_name("static")
ELEVEN_API = "https://api.elevenlabs.io"


async def watch_event_loop(period_s: float = 0.1, warn_s: float = 0.25):
    """Logs when this machine stalls the event loop. A slow turn with no stall
    logged was the network (Riva, Claude or ElevenLabs), not this process."""
    while True:
        start = time.monotonic()
        await asyncio.sleep(period_s)
        stall = time.monotonic() - start - period_s
        if stall > warn_s:
            mark("machine", "EVENT LOOP STALLED", f"{stall:.2f}s (CPU-bound work is blocking audio)")


def create_app(characters_dir: str, default_character: str, opts: SessionOptions, read_only: bool = False) -> FastAPI:
    """read_only: characters can be viewed and tried but not saved (hosts with a
    read-only filesystem, such as Vercel)."""
    app = FastAPI()
    store = CharacterStore(characters_dir, read_only=read_only)
    active: dict[str, asyncio.Task] = {}

    # --- login ---------------------------------------------------------------

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        path = request.url.path
        if path in ("/login", "/logout") or auth.valid(request.cookies.get(auth.COOKIE)):
            return await call_next(request)
        if path.startswith("/api/") or path == "/config":
            return JSONResponse({"error": "Not signed in"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    def login_page(error: str = "", status: int = 200):
        html = (STATIC / "login.html").read_text().replace("<!--ERROR-->", error)
        return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})

    @app.get("/login")
    async def login_form():
        if not auth.enabled():
            return RedirectResponse("/", status_code=303)
        return login_page()

    @app.post("/login")
    async def login(request: Request):
        form = parse_qs((await request.body()).decode(errors="replace"))
        username = (form.get("username") or [""])[0]
        password = (form.get("password") or [""])[0]
        if not await auth.check_credentials(username, password):
            return login_page("Wrong username or password.", 401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            auth.COOKIE, auth.make_cookie(), max_age=auth.SESSION_S, httponly=True,
            samesite="lax", secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        )
        return response

    @app.get("/logout")
    async def logout():
        response = RedirectResponse("/login" if auth.enabled() else "/", status_code=303)
        response.delete_cookie(auth.COOKIE)
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(CharacterError)
    async def character_error(_request, e: CharacterError):
        return JSONResponse({"error": str(e), "errors": e.errors}, status_code=e.status)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/config")
    async def config():
        return {
            "default_character": default_character,
            "barge_in": opts.barge_in,
            "tts": opts.tts,
            "in_rate": IN_SAMPLE_RATE,
            "out_rate": OUT_SAMPLE_RATE,
            "read_only": read_only,
            "login": auth.enabled(),
        }

    # --- characters ---------------------------------------------------------

    @app.get("/api/characters")
    async def list_characters():
        return store.list()

    @app.get("/api/characters/{char_id}")
    async def get_character(char_id: str):
        return store.get(char_id)

    @app.put("/api/characters/{char_id}")
    async def save_character(char_id: str, data: dict = Body(...)):
        store.existing_path(char_id)
        return store.save(char_id, data)

    @app.post("/api/characters")
    async def create_character(data: dict = Body(...)):
        return store.create(data)

    @app.delete("/api/characters/{char_id}")
    async def delete_character(char_id: str):
        store.delete(char_id)
        return {"deleted": char_id}

    @app.get("/api/defaults")
    async def defaults():
        return tuning_defaults()

    @app.post("/api/validate")
    async def validate(data: dict = Body(...)):
        return {"errors": validate_tuning(data), "warnings": warnings_for(data)}

    @app.post("/api/voice-test")
    async def voice_test(body: dict = Body(...)):
        """Speaks a sample line in the given voice settings, so a voice can be
        heard before saving. v3 tags are performed; costs a few characters."""
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            return JSONResponse({"error": "ELEVENLABS_API_KEY is not set in .env"}, status_code=400)
        voice = body.get("voice") or {}
        voice_id = str(voice.get("voice_id", "")).strip()
        if not voice_id:
            return JSONResponse({"error": "Set a voice_id first"}, status_code=400)
        model = voice.get("model") or "eleven_v3_conversational"
        # The conversational v3 model is only served over the dialogue
        # WebSocket; plain v3 over HTTP sounds the same for a sample.
        http_model = "eleven_v3" if model.startswith("eleven_v3") else model
        payload = {"text": str(body.get("text") or "I came here thinking it was nothing.")[:300], "model_id": http_model}
        if voice.get("stability") is not None:
            payload["voice_settings"] = {"stability": voice["stability"]}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{ELEVEN_API}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                headers={"xi-api-key": key},
                json=payload,
            )
        if r.status_code != 200:
            return JSONResponse({"error": f"ElevenLabs answered {r.status_code}: {r.text[:300]}"}, status_code=502)
        return Response(r.content, media_type="audio/mpeg")

    # --- live session -------------------------------------------------------

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        if not auth.valid(websocket.cookies.get(auth.COOKIE)):
            await websocket.close(code=1008)  # policy violation: not signed in
            return
        await websocket.accept()

        # A browser tab gets one conversation: starting again replaces its old
        # session. Other tabs (other people at a demo) are left alone.
        client = websocket.query_params.get("client") or "default"
        old = active.pop(client, None)
        if old is not None:
            old.cancel()

        session_opts = SessionOptions(**{**opts.__dict__})
        barge = websocket.query_params.get("barge_in")
        if barge is not None:
            session_opts.barge_in = barge == "1"

        char_id = websocket.query_params.get("character") or default_character
        try:
            persona_path = str(store.existing_path(char_id))
            persona = PersonaConfig.from_file(persona_path)
            if session_opts.tts:
                from pipeline.tts import VoiceConfig
                VoiceConfig.from_tuning_file(persona_path)
        except (CharacterError, ValueError) as e:
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
            return
        mark("web", "character", f"{char_id} ({persona.scenario.patient_name})")

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
        watchdog = asyncio.create_task(watch_event_loop())
        active[client] = task
        try:
            await task
        except asyncio.CancelledError:
            await session.worker.cancel()
        finally:
            watchdog.cancel()
            if active.get(client) is task:
                del active[client]

    return app


def serve(characters_dir: str, default_character: str, opts: SessionOptions, host: str, port: int):
    import uvicorn

    print(f"\n  Open http://localhost:{port} in your browser (VSCode forwards the port).")
    print("  Use headphones: without them her voice can leak into the mic and trigger barge-in.\n")
    try:
        uvicorn.run(
            create_app(characters_dir, default_character, opts),
            host=host,
            port=port,
            log_level="warning",
            lifespan="off",              # no lifespan traceback on Ctrl+C
            timeout_graceful_shutdown=2,  # do not wait on an open browser socket
        )
    except KeyboardInterrupt:
        pass
    finally:
        # Riva's streaming client runs in a background thread that blocks on
        # its gRPC stream; joining it is what made Ctrl+C hang. Exit directly.
        print("\n  Stopped.")
        os._exit(0)

