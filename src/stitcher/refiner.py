"""LLM-powered refinement — gap analysis, vocabulary extraction, and new search generation."""

from __future__ import annotations

from .llm import LLMClient
from .models import EvaluatedResult, ProjectContext, RefinementResult, SearchBrief
from .prompts.refine import SYSTEM, build_user_prompt


async def refine(
    evaluated: dict[str, list[EvaluatedResult]],
    briefs: list[SearchBrief],
    context: ProjectContext,
    llm: LLMClient,
    model: str,
) -> RefinementResult:
    """Analyze coverage gaps, extract vocabulary from results, and generate new search briefs."""
    # Build rich summaries for the refinement prompt
    subproblem_summaries = []
    for brief in briefs:
        results = evaluated.get(brief.id, [])
        summary = {
            "subproblem": brief.subproblem,
            "queries_used": ", ".join(q.query for q in brief.queries[:5]),
            "results": [
                {
                    "repo": r.search_result.repo.full_name,
                    "stars": r.search_result.repo.stars,
                    "relevance": r.relevance_score,
                    "quality": r.quality_score,
                    "summary": r.summary,
                    "caveats": r.caveats or "",
                }
                for r in results[:5]  # Top 5 per subproblem for more vocabulary
            ],
        }
        subproblem_summaries.append(summary)

    prompt = build_user_prompt(
        project_description=context.description,
        subproblem_summaries=subproblem_summaries,
    )

    result = await llm.complete_structured(
        prompt=prompt,
        response_model=RefinementResult,
        system=SYSTEM,
        model=model,
    )

    return result
