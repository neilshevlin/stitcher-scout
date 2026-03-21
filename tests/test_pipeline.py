"""Tests for the pipeline modules — searcher and evaluator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from stitcher.evaluator import MIN_RELEVANCE, _score_file_for_selection
from stitcher.models import (
    EvaluatedResult,
    RepoInfo,
    SearchBrief,
    SearchQuery,
    SearchResult,
)
from stitcher.searcher import _stratify_repo_query, execute_briefs


# --- Helpers ---


def _make_repo(full_name: str = "org/repo", stars: int = 100, forks: int = 10, **kw) -> RepoInfo:
    defaults = {
        "full_name": full_name,
        "url": f"https://github.com/{full_name}",
        "description": "A repo",
        "stars": stars,
        "forks": forks,
    }
    defaults.update(kw)
    return RepoInfo(**defaults)


def _make_brief(brief_id: str = "b1") -> SearchBrief:
    return SearchBrief(
        id=brief_id,
        subproblem="test subproblem",
        level="component",
        queries=[
            SearchQuery(query="test query", search_type="repository"),
        ],
        relevance_criteria="must be relevant",
    )


def _make_search_result(
    full_name: str = "org/repo",
    brief_id: str = "b1",
    stars: int = 100,
    forks: int = 10,
    file_path: str | None = None,
    **repo_kw,
) -> SearchResult:
    return SearchResult(
        brief_id=brief_id,
        repo=_make_repo(full_name=full_name, stars=stars, forks=forks, **repo_kw),
        file_path=file_path,
    )


# --- Searcher tests ---


@pytest.mark.asyncio
async def test_searcher_deduplicates_by_repo_and_brief():
    """Duplicate repos (same name + brief) are deduplicated, preferring the one with file_path."""
    brief = _make_brief("b1")

    # Two results for same repo+brief: one without file_path, one with
    dup1 = _make_search_result("org/repo", "b1", file_path=None)
    dup2 = _make_search_result("org/repo", "b1", file_path="src/main.py")
    different = _make_search_result("org/other-repo", "b1", file_path=None)

    all_results = [dup1, dup2, different]

    # Mock the GitHubClient so execute_briefs doesn't hit the network
    mock_gh = AsyncMock()
    # search_repos returns our pre-built results
    mock_gh.search_repos = AsyncMock(return_value=all_results)
    # enrich_repo is a no-op
    mock_gh.enrich_repo = AsyncMock()
    # get_repo_info returns the existing repo data
    mock_gh.get_repo_info = AsyncMock(side_effect=lambda name: _make_repo(full_name=name, quality_score=0.5))

    with patch("stitcher.searcher.compute_repo_quality_score", return_value=0.5):
        results = await execute_briefs([brief], mock_gh, min_quality=0.0, stratify=False)

    # Should have 2 unique repo+brief combos (org/repo and org/other-repo)
    repo_names = [r.repo.full_name for r in results]
    assert repo_names.count("org/repo") == 1
    assert repo_names.count("org/other-repo") == 1

    # The org/repo result should be the one with file_path
    org_repo_result = [r for r in results if r.repo.full_name == "org/repo"][0]
    assert org_repo_result.file_path == "src/main.py"


@pytest.mark.asyncio
async def test_searcher_prefilter_skips_zero_signal_repos():
    """Repos with 0 stars AND 0 forks are filtered out before enrichment."""
    brief = _make_brief("b1")

    zero_signal = _make_search_result("org/empty", "b1", stars=0, forks=0)
    has_stars = _make_search_result("org/good", "b1", stars=50, forks=0)

    mock_gh = AsyncMock()
    mock_gh.search_repos = AsyncMock(return_value=[zero_signal, has_stars])
    mock_gh.enrich_repo = AsyncMock()
    mock_gh.get_repo_info = AsyncMock(side_effect=lambda name: _make_repo(full_name=name, quality_score=0.5))

    with patch("stitcher.searcher.compute_repo_quality_score", return_value=0.5):
        results = await execute_briefs([brief], mock_gh, min_quality=0.0, stratify=False)

    repo_names = [r.repo.full_name for r in results]
    assert "org/empty" not in repo_names
    assert "org/good" in repo_names


@pytest.mark.asyncio
async def test_evaluator_filters_low_relevance():
    """Results with relevance below MIN_RELEVANCE are excluded."""
    from stitcher.evaluator import evaluate
    from stitcher.models import ProjectContext

    brief = _make_brief("b1")
    context = ProjectContext(description="a test project", language="python")
    result = _make_search_result("org/repo", "b1", file_path="src/main.py")

    # Mock the GitHubClient
    mock_gh = AsyncMock()
    mock_gh.get_file_content = AsyncMock(return_value="print('hello')")

    # Mock the LLM to return a low-relevance evaluation
    mock_llm = AsyncMock()
    low_eval = EvaluatedResult(
        search_result=result,
        relevance_score=0.1,  # Below MIN_RELEVANCE (0.4)
        quality_score=0.5,
        summary="Not very relevant",
    )
    mock_llm.complete_structured = AsyncMock(return_value=low_eval)

    evaluated = await evaluate(
        results=[result],
        context=context,
        brief=brief,
        gh=mock_gh,
        llm=mock_llm,
        model="fake-model",
    )

    # Low relevance result should be filtered out
    assert len(evaluated) == 0


def test_evaluator_file_selection_prefers_source():
    """_score_file_for_selection ranks source files above docs/tests/config."""
    src_file = "src/stitcher/core.py"
    test_file = "tests/test_core.py"
    doc_file = "docs/guide.md"
    config_file = "setup.py"
    dotfile = ".gitignore"

    src_score = _score_file_for_selection(src_file)
    test_score = _score_file_for_selection(test_file)
    doc_score = _score_file_for_selection(doc_file)
    config_score = _score_file_for_selection(config_file)
    dot_score = _score_file_for_selection(dotfile)

    # Source files in src/ should score highest
    assert src_score > test_score
    assert src_score > doc_score
    assert src_score > config_score
    assert src_score > dot_score

    # Dotfiles and docs should score lowest
    assert doc_score < 0
    assert dot_score < 0


def test_stratify_repo_query_produces_three_variants():
    """_stratify_repo_query expands a repository query into 3 sort variants."""
    query = SearchQuery(
        query="python web framework",
        search_type="repository",
        qualifiers={"language": "python"},
    )

    variants = _stratify_repo_query(query)
    assert len(variants) == 3

    # Unpack sort values
    sorts = [(sort, order) for _, sort, order in variants]
    assert ("stars", "desc") in sorts
    assert ("updated", "desc") in sorts

    # Third variant should have stars:50..500 qualifier
    third_query, third_sort, _ = variants[2]
    assert third_query.qualifiers.get("stars") == "50..500"
    # Original language qualifier should be preserved
    assert third_query.qualifiers.get("language") == "python"


def test_stratify_repo_query_noop_for_code_search():
    """_stratify_repo_query returns the query unchanged for non-repository types."""
    query = SearchQuery(query="import flask", search_type="code")
    variants = _stratify_repo_query(query)
    assert len(variants) == 1
    assert variants[0][0] is query
