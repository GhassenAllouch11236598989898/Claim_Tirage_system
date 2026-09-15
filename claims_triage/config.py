"""
Configuration settings for the Claims Triage System.
Loaded from environment variables with sensible defaults.
"""

import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # App
    app_name: str = "Claims Triage System"
    debug: bool = True
    log_level: str = "INFO"

    # OpenAI
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.1

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "claims_triage"
    postgres_user: str = "claims_user"
    postgres_password: str = "claims_pass"

    # Budget Ceilings
    max_tokens: int = 50000
    max_wall_clock_seconds: float = 300.0  # 5 minutes

    # Human Gate Thresholds
    human_gate_confidence_threshold: float = 0.8
    human_gate_severity_trigger: str = "high"

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_sync_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
