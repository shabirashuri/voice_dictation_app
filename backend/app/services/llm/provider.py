from .base import LLMBase

class DummyLLM(LLMBase):
    async def extract(self, prompt: str, **kwargs):
        # Return placeholder structured update
        return {"updates": []}

    async def generate(self, prompt: str, **kwargs):
        return "AI-generated comment"
