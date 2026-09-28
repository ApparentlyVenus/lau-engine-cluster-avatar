import asyncio

from renderer.claude import aggregate_renderer_stream
from renderer.prompt import build_renderer_message, describe_undertone
from renderer.speculation import speculative_render
from state_engine.engine import apply_turn, build_initial_state
from state_engine.turn_flags import TurnFlags


async def _tokens(text: str):
    for ch in text:
        yield ch


def _chunks(text: str, early: bool = True) -> list[str]:
    async def run():
        return [c async for c in aggregate_renderer_stream(_tokens(text), early_first_chunk=early)]
    return asyncio.run(run())


# --- chunker ---------------------------------------------------------------

def test_first_chunk_can_end_at_a_comma():
    chunks = _chunks("[shocked] Wait, you're telling me it's cancer? I don't understand.")
    assert chunks == ["[shocked] Wait, you're telling me it's cancer?", "I don't understand."]


def test_first_chunk_splits_at_comma_once_long_enough():
    chunks = _chunks("[shocked] Wait, what? No, that can't be right, the last one was nothing.")
    assert chunks[0] == "[shocked] Wait, what? No,"


def test_first_chunk_needs_enough_spoken_text():
    # "[shocked] Wait," has only 5 spoken characters, so no split there.
    chunks = _chunks("[shocked] Wait, what? No, that can't be right, the last one was nothing.")
    assert len(chunks[0].replace("[shocked]", "").strip()) >= 12


def test_first_chunk_never_splits_inside_a_tag():
    chunks = _chunks("I just, [voice breaking] I don't know what to say to that, honestly.")
    for c in chunks:
        assert c.count("[") == c.count("]")


def test_hyphen_self_interruption_is_not_a_boundary():
    chunks = _chunks("Wait- what- what did you just say to me? Say it again.")
    assert not chunks[0].endswith("-")


def test_later_chunks_are_sentences():
    chunks = _chunks("Okay, so what happens now? Do I need surgery right away? I have classes to teach.")
    assert len(chunks) >= 2
    for c in chunks[1:]:
        assert c[-1] in ".?!"


def test_early_first_chunk_can_be_disabled():
    chunks = _chunks("Okay, so what happens now? Do I need surgery?", early=False)
    assert chunks[0].endswith("?")


def test_chunks_reassemble_to_the_original():
    text = "[hesitant] I, um, I thought it was nothing, like last time. [pause] It was nothing last time."
    assert " ".join(_chunks(text)) == text


# --- renderer message stability ---------------------------------------------

def test_undertone_buckets():
    assert describe_undertone(0.05) == "a slight"
    assert describe_undertone(0.25) == "a noticeable"
    assert describe_undertone(0.45) == "a strong"


def test_predicted_state_matches_real_state_when_no_flags(persona):
    state = build_initial_state(persona)
    predicted, _ = apply_turn(state, TurnFlags(), persona)
    real, _ = apply_turn(state, TurnFlags(), persona)
    a = build_renderer_message(persona, predicted, "Hello.", history=["Learner: Hello."])
    b = build_renderer_message(persona, real, "Hello.", history=["Learner: Hello."])
    assert a == b


def test_small_flag_usually_keeps_the_same_message(persona):
    state = build_initial_state(persona)
    predicted, _ = apply_turn(state, TurnFlags(), persona)
    real, _ = apply_turn(state, TurnFlags(logistics_first=0.2), persona)
    a = build_renderer_message(persona, predicted, "x")
    b = build_renderer_message(persona, real, "x")
    assert a == b


def test_disrespect_changes_the_message(persona):
    state = build_initial_state(persona)
    predicted, _ = apply_turn(state, TurnFlags(), persona)
    real, _ = apply_turn(state, TurnFlags(disrespect=1.0), persona)
    a = build_renderer_message(persona, predicted, "x")
    b = build_renderer_message(persona, real, "x")
    assert a != b


# --- speculative render -----------------------------------------------------

class FakeRenderer:
    def __init__(self, delay: float = 0.05):
        self.started: list[str] = []
        self.finished: list[str] = []
        self.delay = delay

    async def stream(self, message: str):
        self.started.append(message)
        for part in (f"{message}-a", f"{message}-b"):
            await asyncio.sleep(self.delay)
            yield part
        self.finished.append(message)


def _run_spec(spec: str, real: str, real_delay: float, renderer: FakeRenderer):
    emitted: list[tuple[float, str]] = []

    async def run():
        loop = asyncio.get_running_loop()
        t0 = loop.time()

        async def real_message():
            await asyncio.sleep(real_delay)
            return real

        async def emit(chunk):
            emitted.append((loop.time() - t0, chunk))

        line, hit = await speculative_render(spec, real_message(), renderer.stream, emit)
        return line, hit

    line, hit = asyncio.run(run())
    return line, hit, emitted


def test_hit_reuses_the_speculative_stream_and_holds_chunks_until_confirmed():
    r = FakeRenderer(delay=0.02)
    line, hit, emitted = _run_spec("S", "S", real_delay=0.15, renderer=r)
    assert hit
    assert r.started == ["S"]
    assert line == "S-a S-b"
    # Chunks were generated by ~0.04s but must not be emitted before 0.15s.
    assert emitted[0][0] >= 0.14


def test_miss_cancels_and_renders_the_real_message():
    r = FakeRenderer(delay=0.05)
    line, hit, emitted = _run_spec("S", "R", real_delay=0.03, renderer=r)
    assert not hit
    assert r.started == ["S", "R"]
    assert "S" not in r.finished
    assert line == "R-a R-b"
    assert all(chunk.startswith("R") for _, chunk in emitted)


def test_hit_is_faster_than_serial():
    r = FakeRenderer(delay=0.05)
    _, hit, emitted = _run_spec("S", "S", real_delay=0.1, renderer=r)
    assert hit
    # Serial would be 0.1 (interpreter) + 0.05 (first chunk) = 0.15.
    assert emitted[0][0] < 0.14


def test_renderer_error_propagates():
    async def broken(message):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    async def run():
        async def real():
            return "S"

        async def emit(chunk):
            pass

        await speculative_render("S", real(), broken, emit)

    try:
        asyncio.run(run())
    except RuntimeError as e:
        assert "boom" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
