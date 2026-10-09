"""Run the whole patient pipeline. One entry point, four ways in:

    python src/run.py web                      browser mic + speakers (default; works in the devcontainer)
    python src/run.py mic                      local mic + speakers via PyAudio (run on your own machine, not in Docker)
    python src/run.py wav clips/a.wav ...      recorded clips in, her replies saved as .wav, full latency incl. TTS
    python src/run.py text                     typed lines, no audio at all

Common options:
    --persona PATH        tuning file (default: src/state_engine/tuning/tuning.json)
    --no-tts              skip ElevenLabs (prints what she would say)
    --tts-model NAME      override the patient's model for this run: eleven_v3_conversational (tags performed)
                          or eleven_flash_v2_5 (fastest, tags stripped)
    --hold SECONDS        silence before the turn ends (default 0.6)
    --smart               smart-turn model instead of the silence timer
    --no-barge-in         she finishes her line even if the learner talks over her
    --no-word-times       do not ask Riva for word timestamps

Needs in .env: ANTHROPIC_API_KEY, NVIDIA_API_KEY, and for voice ELEVENLABS_API_KEY.
Her voice (voice_id, model, stability) is in the patient's tuning file, "voice" section.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

DEFAULT_PERSONA = str(SRC / "state_engine" / "tuning" / "tuning.json")


def check_env(need_tts: bool, persona_path: str | None = None):
    needed = ["ANTHROPIC_API_KEY", "NVIDIA_API_KEY"]
    if need_tts:
        needed += ["ELEVENLABS_API_KEY"]
    missing = [k for k in needed if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}" + (" (or run with --no-tts)" if need_tts else ""))
    if need_tts and persona_path:
        from pipeline.tts import VoiceConfig
        try:
            VoiceConfig.from_tuning_file(persona_path)
        except ValueError as e:
            sys.exit(str(e))


def make_options(args, barge_in_default: bool):
    from pipeline.build import SessionOptions

    opts = SessionOptions()
    opts.tts = not args.no_tts
    opts.tts_model = args.tts_model
    if args.hold is not None:
        opts.hold_s = args.hold
    if args.smart:
        opts.smart_turn = True
    opts.barge_in = barge_in_default and not args.no_barge_in
    if args.no_word_times:
        opts.word_times = False
    return opts


def quiet_logs():
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "WARNING"))


async def run_mic(args):
    try:
        from pipecat.transports.local.audio import (
            LocalAudioTransport,
            LocalAudioTransportParams,
        )
    except ImportError:
        sys.exit(
            "Local mic needs PyAudio (and PortAudio). Inside the devcontainer there is no\n"
            "audio device anyway: use `python src/run.py web` instead. On your own machine:\n"
            "  macOS: brew install portaudio && pip install pyaudio\n"
            "  Ubuntu: sudo apt install portaudio19-dev && pip install pyaudio"
        )
    from pipecat.workers.runner import WorkerRunner

    from pipeline.build import build_session

    opts = make_options(args, barge_in_default=True)
    transport = LocalAudioTransport(LocalAudioTransportParams(
        audio_in_enabled=True, audio_out_enabled=True,
        audio_in_sample_rate=16000, audio_out_sample_rate=24000,
    ))
    session = build_session(args.persona, opts, transport.input(), transport.output())
    print("\nListening. Speak as the doctor; Ctrl+C to stop. Use headphones.\n")
    runner = WorkerRunner()
    await runner.add_workers(session.worker)
    await runner.run()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the patient pipeline.", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("mode", nargs="?", default="web", choices=["web", "mic", "wav", "text"])
    parser.add_argument("clips", nargs="*", help="wav mode: 16 kHz mono 16-bit clips")
    parser.add_argument("--persona", default=DEFAULT_PERSONA)
    parser.add_argument("--no-tts", action="store_true")
    parser.add_argument("--tts-model", default=None)
    parser.add_argument("--hold", type=float, default=None)
    parser.add_argument("--smart", action="store_true")
    parser.add_argument("--no-barge-in", action="store_true")
    parser.add_argument("--no-word-times", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--out", default="out", help="wav mode: where her replies are saved")
    parser.add_argument("--serial", action="store_true", help="text mode: no speculative renderer")
    args = parser.parse_args(argv)

    if args.mode == "text":
        check_env(need_tts=False)
        from tools.text_dry_run import main as text_main
        asyncio.run(text_main(args.persona, args.serial))
        return

    check_env(need_tts=not args.no_tts, persona_path=args.persona)
    quiet_logs()

    if args.mode == "web":
        from web.server import serve
        serve(args.persona, make_options(args, barge_in_default=True), args.host, args.port)
    elif args.mode == "mic":
        asyncio.run(run_mic(args))
    elif args.mode == "wav":
        if not args.clips:
            sys.exit("wav mode needs at least one clip: python src/run.py wav clips/a.wav")
        from tools.wav_run import run_clips
        asyncio.run(run_clips(args.persona, args.clips, make_options(args, barge_in_default=False), args.out))


if __name__ == "__main__":
    main()