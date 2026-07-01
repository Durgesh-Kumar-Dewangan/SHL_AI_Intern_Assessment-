"""Application configuration via environment variables (Pydantic Settings).

No secrets are hardcoded. Copy `.env.example` to `.env` and fill in values,
or set the equivalent environment variables in your hosting provider.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM provider ---
    # "groq" and "gemini" have generous free tiers and work well for this project.
    # "openai" / "anthropic" also supported if you have keys.
    llm_provider: Literal["groq", "gemini", "openai", "anthropic", "openrouter"] = Field(
        default="groq", description="Which LLM backend to call."
    )
    llm_model: str = Field(default="llama-3.3-70b-versatile", description="Model name for the chosen provider.")
    llm_api_key: str = Field(default="", description="API key for the chosen LLM provider.")
    llm_temperature: float = Field(default=0.2)
    llm_max_tokens: int = Field(default=900)
    llm_timeout_seconds: float = Field(default=18.0)

    # --- Retrieval ---
    catalog_path: Path = Field(default=BASE_DIR / "data" / "shl_catalog.json")
    top_k_retrieval: int = Field(default=20, description="Candidates handed to the LLM for grounding.")
    max_recommendations: int = Field(default=10)

    # --- Conversation ---
    max_turns: int = Field(default=8)

    # --- App ---
    app_env: Literal["dev", "prod"] = Field(default="dev")
    log_level: str = Field(default="INFO")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
