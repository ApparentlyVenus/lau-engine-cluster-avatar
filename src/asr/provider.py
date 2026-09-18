from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable

from asr.types import TranscriptEvent


class ASRProvider(ABC):
    @abstractmethod
    async def stream_transcripts(self, audio_chunks: Iterable[bytes]) -> AsyncIterator[TranscriptEvent]:
        ...