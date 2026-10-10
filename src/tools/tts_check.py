"""Why is there no voice? Checks the ElevenLabs key, the patient's voice, and
each way of reaching it, printing exactly what ElevenLabs answers.

    python src/tools/tts_check.py                     # uses the default tuning file
    python src/tools/tts_check.py path/to/tuning.json

Steps:
  1. key works, and which plan it is on
  2. the voice_id from the tuning file is reachable with this key
  3. Flash over plain HTTP              (what --tts-model eleven_flash_v2_5 uses, minus streaming)
  4. eleven_v3 over plain HTTP          (does v3 work at all for this account and voice?)
  5. v3 Text-to-Dialogue WebSocket      (exactly what the pipeline does; prints every server message)

Costs a few seconds of TTS characters.
"""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import httpx  # noqa: E402

from pipeline.tts import VoiceConfig  # noqa: E402

API = "https://api.elevenlabs.io"
TEXT = "[sighs] I came here thinking it was nothing."


def show(label: str, ok: bool, detail: str):
    print(f"{'OK  ' if ok else 'FAIL'}  {label:<34} {detail}")


def body_of(r: httpx.Response) -> str:
    try:
        return json.dumps(r.json())[:400]
    except Exception:
        return r.text[:400]


def rest_checks(key: str, voice: VoiceConfig) -> bool:
    h = {"xi-api-key": key}
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{API}/v1/user/subscription", headers=h)
        if r.status_code == 200:
            sub = r.json()
            show("1. API key", True, f"plan={sub.get('tier')} chars used {sub.get('character_count')}/{sub.get('character_limit')}")
        else:
            show("1. API key", False, f"HTTP {r.status_code} {body_of(r)}")
            if r.status_code == 401:
                return False

        r = c.get(f"{API}/v1/voices/{voice.voice_id}", headers=h)
        if r.status_code == 200:
            v = r.json()
            show("2. voice", True, f"{v.get('name')!r} category={v.get('category')} labels={v.get('labels')}")
        else:
            show("2. voice", False, f"HTTP {r.status_code} {body_of(r)}  (is it added to My Voices?)")

        for label, model in (("3. Flash v2.5 over HTTP", "eleven_flash_v2_5"), ("4. eleven_v3 over HTTP", "eleven_v3")):
            r = c.post(
                f"{API}/v1/text-to-speech/{voice.voice_id}?output_format=pcm_24000",
                headers=h,
                json={"text": TEXT, "model_id": model},
            )
            if r.status_code == 200 and r.content:
                show(label, True, f"{len(r.content) / 2 / 24000:.1f}s of audio")
            else:
                show(label, False, f"HTTP {r.status_code} {body_of(r)}")
    return True


async def dialogue_ws_check(key: str, voice: VoiceConfig, model: str):
    import websockets

    url = f"wss://api.elevenlabs.io/v1/text-to-dialogue/multi-stream-input?model_id={model}&output_format=pcm_24000&sync_alignment=true"
    label = f"5. {model} Text-to-Dialogue WS"
    try:
        ws = await websockets.connect(url, additional_headers={"xi-api-key": key})
    except Exception as e:
        show(label, False, f"could not connect: {e!r}")
        return

    ctx = "check"
    open_msg = {"context_id": ctx, "voices": [voice.voice_id]}
    if voice.stability is not None:
        open_msg["voice_settings"] = {"stability": voice.stability}
    await ws.send(json.dumps(open_msg))
    await ws.send(json.dumps({"context_id": ctx, "inputs": [{"text": TEXT + " ", "voice_id": voice.voice_id, "new_turn": True}]}))
    await ws.send(json.dumps({"context_id": ctx, "flush": True}))

    audio_s = 0.0
    print(f"      server messages ({model}):")
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("audio"):
                audio_s += len(base64.b64decode(msg["audio"])) / 2 / 24000
                print(f"        audio chunk, total {audio_s:.2f}s")
            else:
                print(f"        {json.dumps(msg)[:300]}")
            if msg.get("is_final") or msg.get("error"):
                break
    except asyncio.TimeoutError:
        print("        (no message for 10s)")
    except websockets.ConnectionClosed as e:
        print(f"        connection closed by server: code={e.code} reason={e.reason!r}")
    finally:
        await ws.close()
    show(label, audio_s > 0, f"{audio_s:.1f}s of audio" if audio_s else "no audio came back (see messages above)")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(SRC / "state_engine" / "tuning" / "tuning.json")
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set in .env")
    voice = VoiceConfig.from_tuning_file(path)
    print(f"voice_id={voice.voice_id} model={voice.model} stability={voice.stability}\n")
    try:
        reachable = rest_checks(key, voice)
    except httpx.HTTPError as e:
        sys.exit(f"Could not reach api.elevenlabs.io: {e!r}")
    if reachable:
        asyncio.run(dialogue_ws_check(key, voice, voice.model if voice.model.startswith("eleven_v3") else "eleven_v3_conversational"))
    print(
        "\nHow to read this:\n"
        "  3 OK, 4 FAIL      -> this account or voice cannot use v3; set \"model\": \"eleven_flash_v2_5\" in the tuning file\n"
        "  4 OK, 5 FAIL      -> v3 works but the Text-to-Dialogue WebSocket is not enabled for your workspace,\n"
        "                       or rejects this voice; the messages under step 5 say which\n"
        "  3 FAIL            -> key, plan or voice problem; see the message"
    )


if __name__ == "__main__":
    main()
