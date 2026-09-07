from abc import ABC, abstractmethod

class LLMBase(ABC):
    @abstractmethod
    async def extract(self, prompt: str, **kwargs):
        raise NotImplementedError()

    @abstractmethod
    async def generate(self, prompt: str, **kwargs):
        raise NotImplementedError()
