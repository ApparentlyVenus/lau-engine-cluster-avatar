"""Is speech-to-text working? Checks the NVIDIA key and the hosted Riva
endpoint the same way the pipeline reaches it, and prints what comes back.

    python src/tools/riva_check.py                  # uses ElevenLabs to make a test sentence
    python src/tools/riva_check.py clips/a.wav      # or your own 16 kHz mono 16-bit clip

Steps:
  1. NVIDIA_API_KEY is set
  2. the endpoint is reachable (TCP + TLS to grpc.nvcf.nvidia.com:443)
  3. a stream of silence is accepted   (auth, credits and the model are fine)
  4. real speech comes back as text     (what the app should see when you talk)
"""

import os
import socket
import ssl
import sys
import threading
import time
import wave
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import grpc  # noqa: E402
import riva.client  # noqa: E402

HOST, PORT = "grpc.nvcf.nvidia.com", 443
# Same model the pipeline uses (Pipecat's NvidiaSTTService default).
FUNCTION_ID = "bb0837de-8c7b-481f-9ec8-ef5663e9c1fa"
RATE = 16000
CHUNK_S = 0.1
SENTENCE = "Mrs. Haddad, I'm afraid the biopsy results are not what we hoped."


def show(label: str, ok: bool, detail: str = ""):
    print(f"{'OK  ' if ok else 'FAIL'}  {label:<30} {detail}")


def reachable() -> bool:
    t = time.monotonic()
    try:
        with socket.create_connection((HOST, PORT), timeout=5) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=HOST):
                pass
    except Exception as e:
        show("2. endpoint reachable", False, f"{e!r}  (network, proxy or firewall)")
        return False
    show("2. endpoint reachable", True, f"{(time.monotonic() - t) * 1000:.0f} ms")
    return True


def asr_service(key: str):
    auth = riva.client.Auth(
        uri=f"{HOST}:{PORT}",
        use_ssl=True,
        metadata_args=[["function-id", FUNCTION_ID], ["authorization", f"Bearer {key}"]],
    )
    return riva.client.ASRService(auth)


def streaming_config():
    from pipeline.build import BOOST_SCORE, CLINICAL_WORDS

    cfg = riva.client.StreamingRecognitionConfig(
        config=riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=RATE,
            language_code="en-US",
            max_alternatives=1,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
        ),
        interim_results=True,
    )
    # Same boosted vocabulary as the pipeline, so results here match the app.
    riva.client.add_word_boosting_to_config(cfg.config, CLINICAL_WORDS, BOOST_SCORE)
    return cfg


def paced(pcm: bytes, start: list):
    size = int(RATE * CHUNK_S) * 2
    start.append(time.monotonic())
    for n, off in enumerate(range(0, len(pcm), size)):
        delay = start[0] + (n + 1) * CHUNK_S - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        yield pcm[off:off + size]


def stream(asr, pcm: bytes, timeout_s: float):
    """Streams audio in real time. Returns (events, error) where events are
    (seconds since start, is_final, text). Runs in a thread so a hung stream
    is reported instead of hanging this script."""
    events, error, start = [], [], []

    def run():
        try:
            for resp in asr.streaming_response_generator(audio_chunks=paced(pcm, start), streaming_config=streaming_config()):
                for r in resp.results:
                    if r.alternatives and r.alternatives[0].transcript.strip():
                        events.append((time.monotonic() - start[0], r.is_final, r.alternatives[0].transcript))
        except grpc.RpcError as e:
            error.append(f"gRPC {e.code().name}: {e.details()}")
        except Exception as e:
            error.append(repr(e))

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        error.append(f"no answer after {timeout_s:.0f}s (stream hung: the hosted model may be down or queued)")
    return events, error[0] if error else None


def load_wav(path: str) -> bytes:
    with wave.open(path, "rb") as wf:
        if wf.getframerate() != RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            sys.exit(f"{path} must be 16 kHz, mono, 16-bit")
        return wf.readframes(wf.getnframes())


def speech_from_elevenlabs() -> bytes | None:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None
    import httpx

    from pipeline.tts import VoiceConfig
    try:
        voice = VoiceConfig.from_tuning_file(str(SRC / "state_engine" / "tuning" / "tuning.json"))
    except ValueError:
        return None
    r = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice.voice_id}?output_format=pcm_16000",
        headers={"xi-api-key": key},
        json={"text": SENTENCE, "model_id": "eleven_flash_v2_5"},
        timeout=30,
    )
    return r.content if r.status_code == 200 and r.content else None


def main():
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        show("1. NVIDIA_API_KEY", False, "not set in .env")
        return
    show("1. NVIDIA_API_KEY", True, f"{key[:8]}... ({len(key)} chars)")
    if not reachable():
        return

    asr = asr_service(key)
    t = time.monotonic()
    _, err = stream(asr, bytes(int(RATE * 1.5) * 2), timeout_s=15)
    if err:
        show("3. stream accepted", False, err)
        if "UNAUTHENTICATED" in err or "PERMISSION_DENIED" in err:
            print("      The key is invalid, expired or out of credits: make a new one at build.nvidia.com.")
        return
    show("3. stream accepted", True, f"{time.monotonic() - t:.1f}s for 1.5s of silence")

    if len(sys.argv) > 1:
        pcm, what = load_wav(sys.argv[1]), sys.argv[1]
    else:
        pcm, what = speech_from_elevenlabs(), f"ElevenLabs: {SENTENCE!r}"
        if pcm is None:
            print("SKIP  4. speech -> text              no clip given and ElevenLabs could not make one;"
                  " run with a 16 kHz wav")
            return
    pcm += bytes(int(RATE * 2.0) * 2)  # trailing silence so Riva finalizes
    speech_s = len(pcm) / 2 / RATE - 2.0
    print(f"      streaming {speech_s:.1f}s of speech ({what})")
    events, err = stream(asr, pcm, timeout_s=speech_s + 15)
    for at, final, text in events:
        print(f"        {at:5.2f}s {'FINAL  ' if final else 'interim'} {text!r}")
    finals = [e for e in events if e[1]]
    if err:
        show("4. speech -> text", False, err)
    elif not events:
        show("4. speech -> text", False, "stream worked but no words came back")
    else:
        show("4. speech -> text", bool(finals), f"final {finals[-1][0] - speech_s:+.2f}s after speech ended" if finals else "interims only, no final")


if __name__ == "__main__":
    main()
