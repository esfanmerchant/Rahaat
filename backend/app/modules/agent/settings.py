"""Agent settings live here so the platform settings stay unchanged (same `.env` files as the voice settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    agent_planner: Literal["local", "gemini"] = "local"
    gemini_api_key: str | None = None
    gemini_agent_model: str = "gemini-3.1-flash-lite"
    gemini_agent_thinking: str = "minimal"  # "" = the model's default
    agent_planner_timeout_s: float = 12.0
    agent_step_budget: int = 12


@lru_cache(maxsize=1)
def agent_settings() -> AgentSettings:
    return AgentSettings()
