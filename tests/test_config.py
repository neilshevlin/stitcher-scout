"""Tests for configuration and settings validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from stitcher.config import Settings


class TestConfigValidation:
    def test_missing_github_token_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        # Patch out gh CLI and keychain so they don't provide a token
        with patch("stitcher.auth._get_gh_token", return_value=None), \
             patch("stitcher.auth._keychain_get", return_value=None):
            with pytest.raises(Exception, match="[Gg]ith[Uu]b"):
                Settings(github_token="")

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
        with patch("stitcher.auth._keychain_get", return_value=None):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                Settings(model="claude-sonnet-4-20250514")

    def test_openai_model_needs_openai_key(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("stitcher.auth._keychain_get", return_value=None):
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                Settings(model="gpt-4o")

    def test_ollama_model_no_key_needed(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        s = Settings(model="ollama/llama3")
        assert s.model == "ollama/llama3"

    def test_gh_cli_token_used_when_no_env(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        with patch("stitcher.auth._get_gh_token", return_value="ghp_from_gh_cli"):
            # Re-trigger resolution since GITHUB_TOKEN was cleared
            os.environ.pop("GITHUB_TOKEN", None)
            from stitcher.config import _resolve_github_token_early
            _resolve_github_token_early()
            s = Settings()
            assert s.github_token == "ghp_from_gh_cli"

    def test_keychain_llm_key_used(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("stitcher.auth._keychain_get", return_value="sk-ant-from-keychain"):
            s = Settings(model="claude-sonnet-4-20250514")
            assert s.model == "claude-sonnet-4-20250514"
