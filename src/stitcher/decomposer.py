"""LLM-powered decomposition of a project description into search briefs."""

from __future__ import annotations

from pydantic import BaseModel

from .llm import LLMClient
from .models import ProjectContext, SearchBrief
from .prompts.decompose import SYSTEM, build_user_prompt


class DecompositionResult(BaseModel):
    """Wrapper for structured output from the LLM."""

    briefs: list[SearchBrief]


async def decompose(context: ProjectContext, llm: LLMClient, model: str) -> list[SearchBrief]:
    """Break a project description into searchable sub-problems."""
    prompt = build_user_prompt(
        description=context.description,
        language=context.language,
        dependencies=context.dependencies or None,
    )

    result = await llm.complete_structured(
        prompt=prompt,
        response_model=DecompositionResult,
        system=SYSTEM,
        model=model,
    )

    return result.briefs
