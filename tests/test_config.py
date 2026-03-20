"""Tests for configuration and settings validation."""

from __future__ import annotations

import os

import pytest

from stitcher.config import Settings


class TestConfigValidation:
    def test_missing_github_token_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(Exception, match="github_token"):
            Settings(github_token="")  # pydantic requires non-empty via Field

    def test_valid_config(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        s = Settings()
        assert s.github_token == "ghp_test123"
        assert s.mode == "fast"
        assert s.model == "claude-sonnet-4-20250514"

    def test_invalid_mode_raises(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        with pytest.raises(ValueError, match="Invalid mode"):
            Settings(mode="turbo")

    def test_deep_mode_accepted(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        s = Settings(mode="deep")
        assert s.mode == "deep"

    def test_custom_model(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        s = Settings(model="gpt-4o")
        assert s.model == "gpt-4o"

    def test_missing_llm_key_raises(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            Settings(model="claude-sonnet-4-20250514")

    def test_openai_model_needs_openai_key(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            Settings(model="gpt-4o")

    def test_ollama_model_no_key_needed(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        s = Settings(model="ollama/llama3")
        assert s.model == "ollama/llama3"
