"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model prefix → required env var
_MODEL_KEY_MAP: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gpt": "OPENAI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "o1": "OPENAI_API_KEY",
    "o3": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "together": "TOGETHER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "",  # no key needed for local models
}

_ALL_KEY_NAMES = sorted({v for v in _MODEL_KEY_MAP.values() if v})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    github_token: str = Field(description="GitHub personal access token")

    # LLM model — any litellm-compatible model string.
    # API keys are read from standard env vars: ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
    model: str = Field(
        default="claude-sonnet-4-20250514",
        validation_alias=AliasChoices("model", "STITCHER_MODEL"),
    )

    mode: Literal["fast", "deep"] = Field(
        default="fast",
        validation_alias=AliasChoices("mode", "STITCHER_MODE"),
    )
    max_refinement_loops: int = Field(
        default=3,
        validation_alias=AliasChoices("max_refinement_loops", "STITCHER_MAX_REFINEMENT_LOOPS"),
    )
    max_candidates_per_subproblem: int = Field(
        default=5,
        validation_alias=AliasChoices("max_candidates_per_subproblem", "STITCHER_MAX_CANDIDATES_PER_SUBPROBLEM"),
    )
    max_file_lines: int = Field(
        default=500,
        validation_alias=AliasChoices("max_file_lines", "STITCHER_MAX_FILE_LINES"),
    )

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("fast", "deep"):
            raise ValueError(f"Invalid mode '{v}'. Must be 'fast' or 'deep'.")
        return v

    @model_validator(mode="after")
    def check_llm_api_key(self) -> Settings:
        """Verify the right API key is set for the chosen model."""
        model_lower = self.model.lower()

        # Find which key this model needs
        required_key = ""
        for prefix, key_name in _MODEL_KEY_MAP.items():
            if model_lower.startswith(prefix):
                required_key = key_name
                break

        # Local models (ollama) don't need a key
        if not required_key:
            return self

        if not os.environ.get(required_key):
            raise ValueError(
                f"Model '{self.model}' requires {required_key} to be set. "
                f"Set it in your environment or .env file."
            )
        return self
