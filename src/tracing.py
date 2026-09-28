import time

_process_start = time.monotonic()
_speech_start = None
_marks: dict[str, float] = {}

STAGES = [
    ("last_word", "last speech ends"),
    ("final", "turn detection"),
    ("interp_done", "interpreter call"),
    ("state_done", "state engine"),
    ("render_first_token", "renderer first token"),
    ("first_chunk", "first chunk to TTS"),
    ("render_done", "renderer finished"),
]


def new_turn():
    global _speech_start
    _speech_start = time.monotonic()
    _marks.clear()


def mark(component: str, event: str, detail: str = "", key: str | None = None, overwrite: bool = False):
    now = time.monotonic()
    turn = f"{now - _speech_start:7.3f}s" if _speech_start is not None else "    n/a "
    print(f"[run {now - _process_start:8.3f}s | turn {turn}] {component:<13}{event:<20}{detail}")
    if key and _speech_start is not None and (overwrite or key not in _marks):
        _marks[key] = now


def summary():
    # Stages can now overlap (the renderer starts before the interpreter
    # returns), so print each stage as an offset from the last speech instead
    # of as a gap from the previous stage.
    origin = _marks.get("last_word", min(_marks.values()) if _marks else None)
    print("    --- latency from last speech ---")
    for key, label in STAGES:
        if key not in _marks or key == "last_word":
            continue
        if origin is not None:
            print(f"    {label:<24}at {_marks[key] - origin:6.3f}s")
    if origin is not None and "first_chunk" in _marks:
        print(f"    {'TOTAL to first chunk':<24}{_marks['first_chunk'] - origin:7.3f}s")
    for key in [k for k in _marks if k != "last_word"]:
        del _marks[key]
