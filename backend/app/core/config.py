from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "voice-dictation-app"
    db_url: str = "sqlite:///./test.db"
    stt_provider: str = "assemblyai"
    # Supabase configuration (set in .env or environment)
    supabase_url: str | None = None
    supabase_key: str | None = None
    # Optional direct Postgres connection string for Supabase (used for migrations/DDL)
    supabase_db_url: str | None = None

settings = Settings()
