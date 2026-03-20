"""LLM-powered evaluation of search results by reading actual code."""

from __future__ import annotations

import asyncio
import re

from .github_client import GitHubClient
from .llm import LLMClient
from .models import EvaluatedResult, ProjectContext, SearchBrief, SearchResult
from .prompts.evaluate import SYSTEM, build_user_prompt
from .scoring import compute_candidate_rank, format_quality_signals

# Minimum relevance score to include in results
MIN_RELEVANCE = 0.4


def _extract_search_terms(brief: SearchBrief) -> list[str]:
    """Extract key search terms from a brief for focus scoring."""
    terms: set[str] = set()

    # Extract meaningful words from the subproblem description
    # Split on common delimiters, keep words 3+ chars
    words = re.split(r'[\s,\-/()]+', brief.subproblem.lower())
    # Filter out stop words and very short words
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "into",
        "using", "based", "system", "implementation", "handling",
        "management", "interface", "module", "library", "framework",
    }
    terms.update(w for w in words if len(w) >= 3 and w not in stop_words)

    # Also extract terms from queries
    for q in brief.queries:
        query_words = re.split(r'[\s,\-/()]+', q.query.lower())
        terms.update(w for w in query_words if len(w) >= 3 and w not in stop_words)

    return list(terms)


async def _evaluate_one(
    result: SearchResult,
    brief: SearchBrief,
    context: ProjectContext,
    gh: GitHubClient,
    llm: LLMClient,
    model: str,
    max_lines: int,
) -> EvaluatedResult | None:
    """Evaluate a single search result by fetching code and scoring with LLM."""
    try:
        # Determine which file to read
        file_path = result.file_path
        if not file_path:
            # For repo-level results, try to find a relevant file from the tree
            tree = await gh.get_directory_tree(result.repo.full_name)
            # Pick the first non-config, non-test file as a starting point
            candidates = [
                f for f in tree
                if not f.startswith(".") and not f.lower().startswith("test")
                and f.endswith((".py", ".go", ".js", ".ts", ".rs", ".java"))
            ]
            if not candidates:
                return None
            file_path = candidates[0]

        code = await gh.get_file_content(result.repo.full_name, file_path, max_lines=max_lines)
    except Exception:
        return None

    prompt = build_user_prompt(
        subproblem=brief.subproblem,
        relevance_criteria=brief.relevance_criteria,
        code=code,
        file_path=file_path,
        repo_name=result.repo.full_name,
        repo_description=result.repo.description,
        project_description=context.description,
        quality_signals=format_quality_signals(result.repo),
        project_language=context.language,
    )

    try:
        evaluated = await llm.complete_structured(
            prompt=prompt,
            response_model=EvaluatedResult,
            system=SYSTEM,
            model=model,
        )
        # Attach the original search result
        evaluated.search_result = result
        return evaluated
    except Exception:
        return None


async def evaluate(
    results: list[SearchResult],
    context: ProjectContext,
    brief: SearchBrief,
    gh: GitHubClient,
    llm: LLMClient,
    model: str,
    max_candidates: int = 5,
    max_lines: int = 500,
) -> list[EvaluatedResult]:
    """Evaluate a batch of search results for a single sub-problem."""
    # Extract search terms for focus scoring
    search_terms = _extract_search_terms(brief)

    # Pre-filter: rank by candidate score (blends repo quality + topic focus)
    # This ensures focused libraries beat large unfocused repos
    sorted_results = sorted(
        results,
        key=lambda r: compute_candidate_rank(r.repo, search_terms),
        reverse=True,
    )[:max_candidates]

    semaphore = asyncio.Semaphore(5)

    async def _bounded(result: SearchResult) -> EvaluatedResult | None:
        async with semaphore:
            return await _evaluate_one(result, brief, context, gh, llm, model, max_lines)

    tasks = [_bounded(r) for r in sorted_results]
    evaluated = await asyncio.gather(*tasks)

    # Filter out None results and low-relevance scores, sort by combined score
    valid = [e for e in evaluated if e is not None and e.relevance_score >= MIN_RELEVANCE]
    valid.sort(key=lambda e: (e.relevance_score + e.quality_score) / 2, reverse=True)

    return valid
