from abc import ABC, abstractmethod

class STTBase(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: str):
        raise NotImplementedError()
