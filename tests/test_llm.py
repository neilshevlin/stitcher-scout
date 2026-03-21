"""Tests for the LLM client — structured output parsing, usage tracking, and error handling."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from stitcher.llm import LLMClient, LLMError


# --- Helpers ---


class DummyModel(BaseModel):
    name: str
    score: float


def _make_litellm_response(
    *,
    tool_name: str = "structured_output",
    arguments: str | None = None,
    tool_calls_empty: bool = False,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
):
    """Build a fake litellm response with the same shape as ModelResponse."""
    if tool_calls_empty:
        tool_calls = []
    elif arguments is not None:
        tool_calls = [
            SimpleNamespace(
                function=SimpleNamespace(name=tool_name, arguments=arguments),
            )
        ]
    else:
        tool_calls = None

    message = SimpleNamespace(
        content=None,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


# --- Tests ---


@pytest.mark.asyncio
async def test_complete_structured_parses_tool_call():
    """Valid tool-use response is parsed into a Pydantic model."""
    payload = json.dumps({"name": "test-project", "score": 0.95})
    response = _make_litellm_response(arguments=payload)

    client = LLMClient()
    with patch("stitcher.llm.litellm.acompletion", new_callable=AsyncMock, return_value=response):
        result = await client.complete_structured(
            prompt="test", response_model=DummyModel, model="fake-model"
        )

    assert isinstance(result, DummyModel)
    assert result.name == "test-project"
    assert result.score == 0.95


@pytest.mark.asyncio
async def test_complete_structured_no_tool_calls():
    """Empty tool_calls list raises LLMError."""
    response = _make_litellm_response(tool_calls_empty=True)

    client = LLMClient()
    with patch("stitcher.llm.litellm.acompletion", new_callable=AsyncMock, return_value=response):
        with pytest.raises(LLMError, match="did not return"):
            await client.complete_structured(
                prompt="test", response_model=DummyModel, model="fake-model"
            )


@pytest.mark.asyncio
async def test_complete_structured_wrong_function_name():
    """Tool call with wrong function name raises LLMError."""
    payload = json.dumps({"name": "x", "score": 0.5})
    response = _make_litellm_response(tool_name="wrong_name", arguments=payload)

    client = LLMClient()
    with patch("stitcher.llm.litellm.acompletion", new_callable=AsyncMock, return_value=response):
        with pytest.raises(LLMError, match="did not return"):
            await client.complete_structured(
                prompt="test", response_model=DummyModel, model="fake-model"
            )


@pytest.mark.asyncio
async def test_complete_structured_malformed_json_args():
    """Invalid JSON in function arguments raises an error."""
    response = _make_litellm_response(arguments="{{not json at all")

    client = LLMClient()
    with patch("stitcher.llm.litellm.acompletion", new_callable=AsyncMock, return_value=response):
        with pytest.raises((json.JSONDecodeError, LLMError)):
            await client.complete_structured(
                prompt="test", response_model=DummyModel, model="fake-model"
            )


@pytest.mark.asyncio
async def test_complete_structured_wrong_schema():
    """Valid JSON that doesn't match the Pydantic schema raises ValidationError or LLMError."""
    payload = json.dumps({"unrelated_field": "hello"})
    response = _make_litellm_response(arguments=payload)

    client = LLMClient()
    with patch("stitcher.llm.litellm.acompletion", new_callable=AsyncMock, return_value=response):
        with pytest.raises((Exception,)):  # ValidationError from pydantic
            await client.complete_structured(
                prompt="test", response_model=DummyModel, model="fake-model"
            )


@pytest.mark.asyncio
async def test_token_usage_tracking():
    """After a successful call, get_usage() returns non-zero tokens."""
    payload = json.dumps({"name": "x", "score": 0.5})
    response = _make_litellm_response(
        arguments=payload,
        prompt_tokens=200,
        completion_tokens=80,
        total_tokens=280,
    )

    client = LLMClient()
    with (
        patch("stitcher.llm.litellm.acompletion", new_callable=AsyncMock, return_value=response),
        patch("stitcher.llm.litellm.completion_cost", return_value=0.003),
    ):
        await client.complete_structured(
            prompt="test", response_model=DummyModel, model="fake-model"
        )

    usage = client.get_usage()
    assert usage.prompt_tokens == 200
    assert usage.completion_tokens == 80
    assert usage.total_tokens == 280
    assert usage.total_cost == pytest.approx(0.003)
    assert usage.model == "fake-model"


@pytest.mark.asyncio
async def test_cost_unavailable_on_error():
    """When litellm.completion_cost raises, total_cost becomes None."""
    payload = json.dumps({"name": "x", "score": 0.5})
    response = _make_litellm_response(arguments=payload)

    client = LLMClient()
    with (
        patch("stitcher.llm.litellm.acompletion", new_callable=AsyncMock, return_value=response),
        patch("stitcher.llm.litellm.completion_cost", side_effect=Exception("unknown model")),
    ):
        await client.complete_structured(
            prompt="test", response_model=DummyModel, model="fake-model"
        )

    usage = client.get_usage()
    assert usage.total_cost is None


@pytest.mark.asyncio
async def test_auth_error_raises_immediately():
    """AuthenticationError raises LLMError without retrying."""
    import litellm

    auth_err = litellm.AuthenticationError(
        message="invalid key",
        llm_provider="anthropic",
        model="fake-model",
    )

    mock_acompletion = AsyncMock(side_effect=auth_err)
    client = LLMClient()
    with patch("stitcher.llm.litellm.acompletion", mock_acompletion):
        with pytest.raises(LLMError, match="Authentication failed"):
            await client.complete_structured(
                prompt="test", response_model=DummyModel, model="fake-model"
            )

    # Should only be called once (no retries for auth errors)
    assert mock_acompletion.call_count == 1
