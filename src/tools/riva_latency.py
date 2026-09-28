import os
import sys
import time
import wave

from dotenv import load_dotenv
load_dotenv()

import riva.client

FUNCTION_IDS = {
    "tdt": "d3fe9151-442b-4204-a70d-5fcc597fd610",
    "ctc": "1598d209-5e27-4d3c-8079-4751568b1081",
    "nemotron": "bb0837de-8c7b-481f-9ec8-ef5663e9c1fa",
}
SAMPLE_RATE = 16000
CHUNK_S = 0.1
TAIL_SILENCE_S = 3.0


class Clock:
    def __init__(self):
        self.start = None
        self.speech_end = None


def load_clip(path: str) -> bytes:
    with wave.open(path, "rb") as wf:
        if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16 kHz, mono, 16-bit")
        return wf.readframes(wf.getnframes())


def paced_chunks(pcm: bytes, clock: Clock):
    chunk_bytes = int(SAMPLE_RATE * CHUNK_S) * 2
    padded = pcm + bytes(int(SAMPLE_RATE * TAIL_SILENCE_S) * 2)
    clock.start = time.monotonic()
    clock.speech_end = clock.start + len(pcm) / 2 / SAMPLE_RATE
    for n, offset in enumerate(range(0, len(padded), chunk_bytes)):
        target = clock.start + (n + 1) * CHUNK_S
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        yield padded[offset:offset + chunk_bytes]


def run_clip(asr, config, path: str):
    pcm = load_clip(path)
    clock = Clock()
    first_interim = None
    last_text = None
    last_change = None
    finals = []
    print(f"\n=== {path} ({len(pcm) / 2 / SAMPLE_RATE:.2f}s of audio) ===")

    responses = asr.streaming_response_generator(
        audio_chunks=paced_chunks(pcm, clock),
        streaming_config=config,
    )
    for response in responses:
        now = time.monotonic()
        for result in response.results:
            if not result.alternatives:
                continue
            text = result.alternatives[0].transcript
            if not text.strip():
                continue
            since_start = now - clock.start
            since_end = now - clock.speech_end
            tag = "FINAL  " if result.is_final else "interim"
            print(f"  {tag} audio+{since_start:6.2f}s  speech_end{since_end:+7.2f}s  {text!r}")
            if result.is_final:
                gap = since_start - last_change if last_change is not None else None
                finals.append((since_end, gap))
                last_text = None
            else:
                if first_interim is None:
                    first_interim = since_start
                if text != last_text:
                    last_text = text
                    last_change = since_start
    return first_interim, finals


def parse_args(argv: list[str]):
    model = "tdt"
    stop_history = None
    clips = []
    for arg in argv:
        if arg in FUNCTION_IDS:
            model = arg
        elif arg.startswith("--stop-history="):
            stop_history = int(arg.split("=", 1)[1])
        else:
            clips.append(arg)
    return model, stop_history, clips


def main(argv: list[str]):
    model, stop_history, clips = parse_args(argv)
    if not clips:
        print("usage: python -m tools.riva_latency [tdt|ctc|nemotron] [--stop-history=MS] clip1.wav [clip2.wav ...]")
        return

    auth = riva.client.Auth(
        uri="grpc.nvcf.nvidia.com:443",
        use_ssl=True,
        metadata_args=[
            ["function-id", FUNCTION_IDS[model]],
            ["authorization", f"Bearer {os.environ['NVIDIA_API_KEY']}"],
        ],
    )
    asr = riva.client.ASRService(auth)
    recognition_config = riva.client.RecognitionConfig(
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hertz=SAMPLE_RATE,
        language_code="en-US",
        max_alternatives=1,
        enable_automatic_punctuation=True,
    )
    if stop_history is not None:
        riva.client.add_endpoint_parameters_to_config(
            recognition_config, -1, -1.0, stop_history, -1.0, -1, -1.0
        )
    config = riva.client.StreamingRecognitionConfig(config=recognition_config, interim_results=True)

    print(f"model: {model}  stop_history: {stop_history if stop_history is not None else 'server default'}")
    rows = []
    for path in clips:
        try:
            first_interim, finals = run_clip(asr, config, path)
            rows.append((path, first_interim, finals))
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")

    print("\n--- summary ---")
    for path, first_interim, finals in rows:
        first = f"{first_interim:.2f}s" if first_interim is not None else "none"
        waits = ", ".join(f"{w:+.2f}s" for w, _ in finals) or "none"
        gaps = ", ".join(f"{g:.2f}s" for _, g in finals if g is not None) or "none"
        split = "  <-- SPLIT" if len(finals) > 1 else ""
        print(f"{path}: first interim at audio+{first} | final after speech end: {waits} | text stable -> final: {gaps}{split}")


if __name__ == "__main__":
    main(sys.argv[1:])