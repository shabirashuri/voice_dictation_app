from pydantic import BaseSettings

class Settings(BaseSettings):
    app_name: str = "voice-dictation-app"
    db_url: str = "sqlite:///./test.db"
    stt_provider: str = "assemblyai"

settings = Settings()
