import time

_process_start = time.monotonic()
_speech_start = None
_marks: dict[str, float] = {}
_turn_open = False

# Set by the runner when a TTS service is in the pipeline. The summary then
# waits for her first audio instead of printing when the renderer finishes.
AUDIO_STAGE = False

STAGES = [
    ("last_word", "last speech ends"),
    ("final", "turn detection"),
    ("interp_done", "interpreter call"),
    ("state_done", "state engine"),
    ("render_first_token", "renderer first token"),
    ("first_chunk", "first chunk to TTS"),
    ("render_done", "renderer finished"),
    ("first_audio", "first audio out"),
]

_listeners = []


def on_summary(fn):
    """fn(dict) is called with each turn's latency summary (used by the web UI)."""
    _listeners.append(fn)


def new_turn():
    global _speech_start, _turn_open
    _speech_start = time.monotonic()
    _turn_open = True
    _marks.clear()


def begin_turn_if_idle():
    """Live sessions: the learner started speaking. Mid-turn restarts keep the turn."""
    if not _turn_open:
        new_turn()


def mark(component: str, event: str, detail: str = "", key: str | None = None, overwrite: bool = False):
    now = time.monotonic()
    turn = f"{now - _speech_start:7.3f}s" if _speech_start is not None else "    n/a "
    print(f"[run {now - _process_start:8.3f}s | turn {turn}] {component:<13}{event:<20}{detail}")
    if key and _speech_start is not None and (overwrite or key not in _marks):
        _marks[key] = now


def render_finished():
    if not AUDIO_STAGE:
        summary()


def audio_started():
    if "first_audio" in _marks or "final" not in _marks:
        return  # not a reply to a learner turn (a filler line), or already counted
    mark("tts", "first audio out", key="first_audio")
    summary()


def summary():
    global _turn_open
    # Stages can overlap (the renderer starts before the interpreter returns),
    # so each stage is printed as an offset from the last speech.
    origin = _marks.get("last_word", min(_marks.values()) if _marks else None)
    result = {}
    print("    --- latency from last speech ---")
    for key, label in STAGES:
        if key not in _marks or key == "last_word":
            continue
        if origin is not None:
            result[key] = round(_marks[key] - origin, 3)
            print(f"    {label:<24}at {result[key]:6.3f}s")
    for key, label in (("first_audio", "first audio"), ("first_chunk", "first chunk")):
        if origin is not None and key in _marks:
            print(f"    {'TOTAL to ' + label:<24}{_marks[key] - origin:7.3f}s")
            break
    for fn in _listeners:
        try:
            fn(result)
        except Exception:  # noqa: BLE001, S110
            pass
    for key in [k for k in _marks if k != "last_word"]:
        del _marks[key]
    _turn_open = False
