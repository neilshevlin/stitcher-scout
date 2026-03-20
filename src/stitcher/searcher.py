"""Search executor — fans out queries from search briefs against the GitHub API.

Key strategy: search stratification. For each repository query, we automatically
run 3 variants to diversify results:
  1. sort:stars — finds the famous, well-known projects
  2. sort:updated — finds actively maintained work
  3. stars:50..500 — the "sweet spot" of real-but-not-famous projects
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .github_client import GitHubClient
from .models import SearchBrief, SearchQuery, SearchResult
from .scoring import compute_repo_quality_score

logger = logging.getLogger("stitcher.searcher")

# Minimum quality score to keep a result (filters out 0-star personal repos)
MIN_QUALITY_SCORE = 0.15

# Qualifiers that only work on repository search, not code search
_REPO_ONLY_QUALIFIERS = {"stars", "forks", "size", "followers", "created", "pushed", "topics", "sort", "order"}


def _filter_qualifiers(qualifiers: dict[str, str], search_type: str) -> dict[str, str]:
    """Strip qualifiers that are invalid for a given search type."""
    if search_type == "code":
        return {k: v for k, v in qualifiers.items() if k not in _REPO_ONLY_QUALIFIERS}
    return qualifiers


def _stratify_repo_query(query: SearchQuery) -> list[tuple[SearchQuery, str, str]]:
    """Expand a single repo search query into stratified variants.

    Returns list of (query, sort, order) tuples.
    """
    if query.search_type != "repository":
        return [(query, "", "")]

    variants: list[tuple[SearchQuery, str, str]] = []

    # Variant 1: sort by stars (the original, finds famous projects)
    variants.append((query, "stars", "desc"))

    # Variant 2: sort by recently updated (finds actively maintained work)
    variants.append((query, "updated", "desc"))

    # Variant 3: mid-range stars (the sweet spot of real-but-not-famous)
    # Override the stars qualifier to target 50-500 range
    mid_query = SearchQuery(
        query=query.query,
        search_type=query.search_type,
        qualifiers={**query.qualifiers, "stars": "50..500"},
    )
    variants.append((mid_query, "stars", "desc"))

    return variants


async def _run_single_query(
    brief: SearchBrief,
    query: SearchQuery,
    gh: GitHubClient,
    sort: str = "",
    order: str = "desc",
) -> list[SearchResult]:
    """Run a single search query and tag results with the brief ID."""
    qualifiers = _filter_qualifiers(query.qualifiers, query.search_type)
    try:
        if query.search_type == "code":
            results = await gh.search_code(query.query, qualifiers, per_page=10)
        elif query.search_type == "repository":
            results = await gh.search_repos(
                query.query, qualifiers, per_page=8,
                sort=sort or "stars", order=order,
            )
        elif query.search_type == "topic":
            topic_qualifiers = {**qualifiers, "topic": query.query}
            results = await gh.search_repos("", topic_qualifiers, per_page=8)
        else:
            return []
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HTTP %s for query %r (brief=%s, type=%s): %s",
            exc.response.status_code, query.query, brief.id, query.search_type, exc,
        )
        return []
    except httpx.TimeoutException as exc:
        logger.warning(
            "Timeout for query %r (brief=%s, type=%s): %s",
            query.query, brief.id, query.search_type, exc,
        )
        return []
    except (httpx.RequestError, ValueError, KeyError) as exc:
        logger.warning(
            "Request/parse error for query %r (brief=%s, type=%s): %s",
            query.query, brief.id, query.search_type, exc,
        )
        return []

    # Tag results with the brief that produced them
    for r in results:
        r.brief_id = brief.id
    return results


async def _enrich_result(result: SearchResult, gh: GitHubClient) -> SearchResult:
    """Fetch full repo metadata and compute quality score."""
    try:
        full_repo = await gh.get_repo_info(result.repo.full_name)
        result.repo = full_repo
        await gh.enrich_repo(result.repo)
        result.repo.quality_score = compute_repo_quality_score(result.repo)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HTTP %s enriching repo %s: %s",
            exc.response.status_code, result.repo.full_name, exc,
        )
        result.repo.quality_score = compute_repo_quality_score(result.repo)
    except httpx.TimeoutException as exc:
        logger.warning("Timeout enriching repo %s: %s", result.repo.full_name, exc)
        result.repo.quality_score = compute_repo_quality_score(result.repo)
    except (httpx.RequestError, ValueError, KeyError) as exc:
        logger.warning("Error enriching repo %s: %s", result.repo.full_name, exc)
        result.repo.quality_score = compute_repo_quality_score(result.repo)
    return result


async def execute_briefs(
    briefs: list[SearchBrief],
    gh: GitHubClient,
    min_quality: float = MIN_QUALITY_SCORE,
    stratify: bool = True,
) -> list[SearchResult]:
    """Execute all search queries from all briefs, deduplicate, enrich, and filter.

    When stratify=True, each repository query is automatically expanded into
    3 variants (by stars, by recently updated, mid-range stars) to diversify results.
    """
    # 1. Build all search tasks, applying stratification to repo queries
    tasks = []
    for brief in briefs:
        for query in brief.queries:
            if stratify and query.search_type == "repository":
                for variant_query, sort, order in _stratify_repo_query(query):
                    tasks.append(_run_single_query(brief, variant_query, gh, sort=sort, order=order))
            else:
                tasks.append(_run_single_query(brief, query, gh))

    all_results: list[SearchResult] = []
    for batch in await asyncio.gather(*tasks):
        all_results.extend(batch)

    # 2. Deduplicate by repo+brief (keep the one with file_path if available)
    seen: dict[str, SearchResult] = {}
    for r in all_results:
        if r.repo.archived:
            continue
        key = f"{r.repo.full_name}:{r.brief_id}"
        existing = seen.get(key)
        if existing is None:
            seen[key] = r
        elif r.file_path and not existing.file_path:
            seen[key] = r

    deduped = list(seen.values())

    # 3. Enrich unique repos with full metadata + quality signals
    unique_repos: dict[str, SearchResult] = {}
    for r in deduped:
        if r.repo.full_name not in unique_repos:
            unique_repos[r.repo.full_name] = r

    semaphore = asyncio.Semaphore(10)

    async def _bounded_enrich(result: SearchResult) -> SearchResult:
        async with semaphore:
            return await _enrich_result(result, gh)

    enriched_raw = await asyncio.gather(
        *[_bounded_enrich(r) for r in unique_repos.values()],
        return_exceptions=True,
    )

    # Filter out exceptions from the gather results
    enriched: list[SearchResult] = []
    for i, r in enumerate(enriched_raw):
        if isinstance(r, BaseException):
            repo_name = list(unique_repos.values())[i].repo.full_name
            logger.warning("Unhandled error enriching repo %s: %s", repo_name, r)
        else:
            enriched.append(r)

    # Build a map of enriched repo data
    repo_map: dict[str, SearchResult] = {}
    for r in enriched:
        repo_map[r.repo.full_name] = r

    # Apply enriched repo data back to all results
    for r in deduped:
        enriched_r = repo_map.get(r.repo.full_name)
        if enriched_r:
            r.repo = enriched_r.repo

    # 4. Filter by minimum quality score
    filtered = [r for r in deduped if r.repo.quality_score >= min_quality]

    # 5. Sort by quality score (best first)
    filtered.sort(key=lambda r: r.repo.quality_score, reverse=True)

    return filtered
