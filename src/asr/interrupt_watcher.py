import time

from interpreter.interruption import should_interrupt

from asr.provider import ASRProvider


class InterruptWatcher:
    def __init__(self, asr_provider: ASRProvider, tuning: dict, patient_state_getter, on_interrupt):
        self.asr_provider = asr_provider
        self.tuning = tuning
        self.get_patient_state = patient_state_getter
        self.on_interrupt = on_interrupt
        self.turn_start_time = None
        self.last_interruption_time = 0.0
        self.interrupted_this_turn = False

    async def watch(self, audio_chunks):
        async for event in self.asr_provider.stream_transcripts(audio_chunks):
            if self.interrupted_this_turn:
                continue

            if self.turn_start_time is None:
                self.turn_start_time = time.monotonic()

            seconds_speaking = time.monotonic() - self.turn_start_time
            seconds_since_last_interruption = time.monotonic() - self.last_interruption_time

            state = self.get_patient_state()
            if should_interrupt(state, seconds_speaking, seconds_since_last_interruption, self.tuning):
                self.interrupted_this_turn = True
                self.last_interruption_time = time.monotonic()
                await self.on_interrupt()

    def reset_for_new_turn(self):
        self.turn_start_time = None
        self.interrupted_this_turn = False