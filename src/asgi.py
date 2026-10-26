"""ASGI entrypoint for hosted deployments (Vercel finds `app` in src/asgi.py;
any ASGI server works: `uvicorn asgi:app --app-dir src`).

Configuration comes from the environment:
    ANTHROPIC_API_KEY, NVIDIA_API_KEY, ELEVENLABS_API_KEY   required
    APP_USERNAME, APP_PASSWORD (, APP_SECRET)               the login (web/auth.py)
    CHARACTERS_READONLY=1                                   no saving characters (automatic on Vercel)
    DEFAULT_CHARACTER                                       selected when the page opens (default: tuning)
    NO_TTS=1                                                text only, no voice

Locally, `python src/run.py web` is still the way to run it.
"""

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from pipeline.build import SessionOptions  # noqa: E402
from web.server import create_app  # noqa: E402

opts = SessionOptions()
opts.tts = os.environ.get("NO_TTS", "") not in ("1", "true")

# Vercel's filesystem is read-only, so saving characters cannot work there.
read_only = os.environ.get("CHARACTERS_READONLY", "1" if os.environ.get("VERCEL") else "") in ("1", "true")

app = create_app(
    str(SRC / "state_engine" / "tuning"),
    os.environ.get("DEFAULT_CHARACTER", "tuning"),
    opts,
    read_only=read_only,
)
