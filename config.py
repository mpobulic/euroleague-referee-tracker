from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://referee:referee@localhost:5432/referee_tracker"
    )

    # OpenAI
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")
    openai_vision_detail: str = Field(default="high")  # "low" | "high" | "auto"

    # Euroleague API
    euroleague_api_base: str = Field(default="https://api.euroleague.net")
    euroleague_competition_code: str = Field(default="E")

    # Video
    video_storage_path: str = Field(default="/data/videos")
    frame_storage_path: str = Field(default="/data/frames")
    ydl_cookies_file: str | None = Field(default=None)

    # App
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    secret_key: str = Field(default="change-me-in-production")

    # Workers
    ingestion_workers: int = Field(default=4)
    video_workers: int = Field(default=2)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
