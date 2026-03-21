"""Application settings loaded from environment variables and credential chain."""

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


def _resolve_github_token_early() -> str | None:
    """Try to resolve GitHub token before pydantic validation.

    This runs the non-interactive part of the credential chain
    (env var, gh CLI, keychain) and sets GITHUB_TOKEN in the
    environment so pydantic-settings can find it.
    """
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]

    from .auth import resolve_github_token
    token = resolve_github_token(interactive=False)
    if token:
        os.environ["GITHUB_TOKEN"] = token
    return token


def _resolve_llm_key_early(model: str) -> str | None:
    """Try to resolve LLM API key before pydantic validation."""
    from .auth import resolve_llm_key
    return resolve_llm_key(model, interactive=False)


# Run GitHub token resolution at import time so pydantic can find it
_resolve_github_token_early()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    github_token: str = Field(default="", description="GitHub personal access token")

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
    max_runtime: int = Field(
        default=300,
        description="Pipeline-level timeout in seconds",
        validation_alias=AliasChoices("max_runtime", "STITCHER_MAX_RUNTIME"),
    )
    max_evaluations: int = Field(
        default=30,
        description="Max LLM evaluations per run",
        validation_alias=AliasChoices("max_evaluations", "STITCHER_MAX_EVALUATIONS"),
    )

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("fast", "deep"):
            raise ValueError(f"Invalid mode '{v}'. Must be 'fast' or 'deep'.")
        return v

    @model_validator(mode="after")
    def apply_deep_mode_defaults(self) -> Settings:
        """Bump budget limits when mode is 'deep', unless explicitly set."""
        if self.mode == "deep":
            # If the value is still at the fast-mode default, upgrade it
            if self.max_runtime == 300:
                self.max_runtime = 600
            if self.max_evaluations == 30:
                self.max_evaluations = 60
        return self

    @model_validator(mode="after")
    def check_github_token(self) -> Settings:
        """Verify GitHub token is available."""
        if not self.github_token:
            raise ValueError(
                "GitHub token not found. Set GITHUB_TOKEN, run 'stitcher setup', "
                "or install the gh CLI (https://cli.github.com)."
            )
        return self

    @model_validator(mode="after")
    def check_llm_api_key(self) -> Settings:
        """Verify the right API key is set for the chosen model."""
        # Try the credential chain (keychain, etc.) before failing
        _resolve_llm_key_early(self.model)

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
                f"Run 'stitcher setup' or set it in your environment."
            )
        return self
