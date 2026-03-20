"""LLM client wrapper with structured output via tool-use. Supports any provider via litellm."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TypeVar

import litellm
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger("stitcher.llm")

# Suppress litellm's noisy default logging
litellm.suppress_debug_info = True

MAX_RETRIES = 3
RETRY_DELAY = 2.0


class LLMError(Exception):
    """Raised when an LLM call fails after retries."""


class LLMClient:
    """Provider-agnostic LLM client powered by litellm.

    Model strings follow litellm conventions:
        - "claude-sonnet-4-20250514" (auto-detected as Anthropic)
        - "gpt-4o" (auto-detected as OpenAI)
        - "anthropic/claude-sonnet-4-20250514" (explicit provider prefix)
        - "openai/gpt-4o"
        - "gemini/gemini-2.0-flash"
        - "ollama/llama3" (local models)

    API keys are read from standard environment variables:
        ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, etc.
    """

    async def complete(self, prompt: str, system: str = "", model: str = "claude-sonnet-4-20250514") -> str:
        """Simple text completion."""
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._call_with_retry(model=model, messages=messages, max_tokens=4096)
        return response.choices[0].message.content or ""

    async def complete_structured(
        self,
        prompt: str,
        response_model: type[T],
        system: str = "",
        model: str = "claude-sonnet-4-20250514",
    ) -> T:
        """Get structured output by using tool-use to force a JSON response matching the pydantic model."""
        tool_name = "structured_output"
        tool_schema = response_model.model_json_schema()

        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"Output structured data matching the {response_model.__name__} schema.",
                    "parameters": tool_schema,
                },
            }
        ]

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._call_with_retry(
            model=model,
            messages=messages,
            max_tokens=4096,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": tool_name}},
        )

        message = response.choices[0].message
        if message.tool_calls:
            for tool_call in message.tool_calls:
                if tool_call.function.name == tool_name:
                    args = json.loads(tool_call.function.arguments)
                    return response_model.model_validate(args)

        raise LLMError(f"LLM did not return a {tool_name} tool call. Model may not support tool use.")

    async def _call_with_retry(self, **kwargs) -> litellm.ModelResponse:
        """Call litellm.acompletion with retry logic for transient failures."""
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await litellm.acompletion(**kwargs)
            except litellm.RateLimitError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt
                    logger.warning(f"Rate limited (attempt {attempt}/{MAX_RETRIES}), retrying in {wait}s...")
                    await asyncio.sleep(wait)
            except litellm.AuthenticationError as e:
                # Don't retry auth failures — they won't resolve
                provider = kwargs.get("model", "unknown").split("/")[0]
                raise LLMError(
                    f"Authentication failed for model '{kwargs.get('model')}'. "
                    f"Check that the correct API key is set (e.g. ANTHROPIC_API_KEY, OPENAI_API_KEY)."
                ) from e
            except litellm.NotFoundError as e:
                raise LLMError(
                    f"Model '{kwargs.get('model')}' not found. "
                    f"Check the model name — litellm expects names like 'claude-sonnet-4-20250514', 'gpt-4o', 'gemini/gemini-2.0-flash'."
                ) from e
            except (litellm.APIConnectionError, litellm.Timeout, litellm.InternalServerError) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt
                    logger.warning(f"Transient error (attempt {attempt}/{MAX_RETRIES}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
            except litellm.APIError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt
                    logger.warning(f"API error (attempt {attempt}/{MAX_RETRIES}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)

        raise LLMError(f"LLM call failed after {MAX_RETRIES} attempts: {last_error}")
