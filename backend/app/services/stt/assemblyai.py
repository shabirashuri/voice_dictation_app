from .base import STTBase

class AssemblyAI(STTBase):
    def __init__(self, api_key: str = None):
        self.api_key = api_key

    async def transcribe(self, audio_path: str):
        # Placeholder for AssemblyAI integration
        return "transcript chunk"
