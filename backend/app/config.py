"""Centralized, typed runtime configuration for Plan B."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    asr_provider: str
    tts_provider: str

    @property
    def provider_configured(self) -> bool:
        values = (self.llm_api_key, self.llm_model, self.llm_base_url)
        placeholders = ("replace", "provider.example", "server-only", "your-")
        return all(values) and not any(
            marker in value.lower() for value in values for marker in placeholders
        )


def load_settings() -> Settings:
    database_path = Path(os.getenv("PLANB_DB", "planb.sqlite3"))
    if not database_path.is_absolute():
        database_path = BACKEND_ROOT / database_path
    return Settings(
        database_path=database_path,
        llm_provider=os.getenv("LLM_PROVIDER", "deterministic"),
        llm_model=os.getenv("LLM_MODEL", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        asr_provider=os.getenv("ASR_PROVIDER", "browser"),
        tts_provider=os.getenv("TTS_PROVIDER", "none"),
    )


settings = load_settings()
