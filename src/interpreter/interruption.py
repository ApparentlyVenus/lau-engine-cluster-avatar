import asyncio
import random
from state_engine.patient_state import EmotionMode

INTERRUPT_LINE_BANK = {
    "anger_interrupt": [
        "No, wait.",
        "You're not even listening to me.",
    ],
    "panic_interrupt": [
        "Wait, what- what did you just say?",
        "Hold on, I don't- slow down.",
    ],
}

_last_used_line = {}


def select_interrupt_category(state):
    if state.emotion.primary == EmotionMode.ANGER:
        return "anger_interrupt"
    if state.emotion.primary == EmotionMode.FEAR:
        return "panic_interrupt"
    return None


def pick_line(category: str) -> str:
    lines = INTERRUPT_LINE_BANK[category]
    last = _last_used_line.get(category)
    choices = [line for line in lines if line != last] or lines
    chosen = random.choice(choices)
    _last_used_line[category] = chosen
    return chosen


async def handle_interrupt(state, renderer_call, tts_call, play_audio):
    category = select_interrupt_category(state)
    if category is None:
        return

    filler_line = pick_line(category)

    filler_audio_task = asyncio.create_task(tts_call(filler_line))
    full_response_task = asyncio.create_task(
        generate_interrupt_continuation(state, filler_line, renderer_call, tts_call)
    )

    filler_audio = await filler_audio_task
    await play_audio(filler_audio)

    full_audio = await full_response_task
    await play_audio(full_audio)