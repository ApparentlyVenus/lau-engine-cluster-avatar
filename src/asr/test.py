import asyncio
import wave

from asr.riva_provider import RivaASRProvider


def read_wav_chunks(path, chunk_size=1600):
    with wave.open(path, "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        while True:
            data = wf.readframes(chunk_size)
            if not data:
                break
            yield data


async def main():
    provider = RivaASRProvider()
    audio_chunks = read_wav_chunks("test_audio.wav")

    async for event in provider.stream_transcripts(audio_chunks):
        marker = "FINAL" if event.is_final else "partial"
        print(f"[{marker}] {event.text}")


if __name__ == "__main__":
    asyncio.run(main())