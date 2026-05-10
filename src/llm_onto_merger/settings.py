from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_model: str
    ollama_host: str = "http://localhost:11434"
    save_location: Path = Path("tests/outputs")


settings = Settings()
