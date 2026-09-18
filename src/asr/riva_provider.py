import asyncio
import os
import queue
import threading

import riva.client

from asr.provider import ASRProvider
from asr.types import TranscriptEvent

PARAKEET_FUNCTION_ID = "d3fe9151-442b-4204-a70d-5fcc597fd610"

class RivaASRProvider(ASRProvider):
    def __init__(self):
        api_key = os.environ["NVIDIA_API_KEY"]
        self.auth = riva.client.Auth(
            uri="grpc.nvcf.nvidia.com:443",
            use_ssl=True,
            metadata_args=[
                ["function-id", PARAKEET_FUNCTION_ID],
                ["authorization", f"Bearer {api_key}"],
            ],
        )
        self.asr_service = riva.client.ASRService(self.auth)

    def _build_config(self):
        recognition_config = riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=16000,
            language_code="en-US",
            max_alternatives=1,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
        )
        return riva.client.StreamingRecognitionConfig(
            config=recognition_config,
            interim_results=True,
        )

    async def stream_transcripts(self, audio_chunks):
        event_queue: queue.Queue = queue.Queue()
        stop_signal = object()

        def run_streaming():
            config = self._build_config()
            responses = self.asr_service.streaming_response_generator(
                audio_chunks=audio_chunks,
                streaming_config=config,
            )
            try:
                for response in responses:
                    for result in response.results:
                        if not result.alternatives:
                            continue
                        event_queue.put(TranscriptEvent(
                            text=result.alternatives[0].transcript,
                            is_final=result.is_final,
                            stability=result.stability,
                        ))
            finally:
                event_queue.put(stop_signal)

        thread = threading.Thread(target=run_streaming, daemon=True)
        thread.start()

        loop = asyncio.get_event_loop()
        while True:
            item = await loop.run_in_executor(None, event_queue.get)
            if item is stop_signal:
                break
            yield item