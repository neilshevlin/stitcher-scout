"""Tests for credential resolution chain."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from stitcher.auth import resolve_github_token, resolve_llm_key, _get_gh_token


class TestGitHubTokenResolution:
    def test_env_var_takes_priority(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
        token = resolve_github_token()
        assert token == "ghp_from_env"

    def test_gh_cli_used_when_no_env(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("stitcher.auth._get_gh_token", return_value="ghp_from_gh"):
            token = resolve_github_token()
            assert token == "ghp_from_gh"

    def test_keychain_used_when_no_env_or_gh(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("stitcher.auth._get_gh_token", return_value=None), \
             patch("stitcher.auth._keychain_get", return_value="ghp_from_keychain"):
            token = resolve_github_token()
            assert token == "ghp_from_keychain"

    def test_returns_none_when_nothing_found(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("stitcher.auth._get_gh_token", return_value=None), \
             patch("stitcher.auth._keychain_get", return_value=None):
            token = resolve_github_token(interactive=False)
            assert token is None


class TestLLMKeyResolution:
    def test_env_var_takes_priority(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
        key = resolve_llm_key("claude-sonnet-4-20250514")
        assert key == "sk-ant-from-env"

    def test_keychain_used_when_no_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("stitcher.auth._keychain_get", return_value="sk-ant-from-keychain"):
            key = resolve_llm_key("claude-sonnet-4-20250514")
            assert key == "sk-ant-from-keychain"

    def test_ollama_needs_no_key(self, monkeypatch):
        key = resolve_llm_key("ollama/llama3")
        assert key == ""

    def test_openai_model_checks_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        key = resolve_llm_key("gpt-4o")
        assert key == "sk-openai-test"

    def test_returns_none_when_nothing_found(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("stitcher.auth._keychain_get", return_value=None):
            key = resolve_llm_key("claude-sonnet-4-20250514", interactive=False)
            assert key is None


class TestGhCliToken:
    def test_returns_none_when_gh_not_installed(self):
        with patch("shutil.which", return_value=None):
            assert _get_gh_token() is None

    def test_returns_token_from_gh(self):
        with patch("shutil.which", return_value="/usr/bin/gh"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "ghp_test_token\n"
            assert _get_gh_token() == "ghp_test_token"

    def test_returns_none_on_gh_failure(self):
        with patch("shutil.which", return_value="/usr/bin/gh"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            assert _get_gh_token() is None
