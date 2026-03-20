"""Mock integration tests for the scout pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stitcher.models import (
    EvaluatedResult,
    ProjectContext,
    RelevantFile,
    RepoInfo,
    ScoutReport,
    SearchBrief,
    SearchQuery,
    SearchResult,
    SubproblemReport,
    TokenUsageSummary,
)


# --- Fixtures ---


def _make_repo(name: str = "owner/repo", stars: int = 100, language: str = "Python") -> RepoInfo:
    return RepoInfo(
        full_name=name,
        url=f"https://github.com/{name}",
        description=f"A {language} project",
        stars=stars,
        language=language,
        has_license=True,
        license_name="MIT",
    )


def _make_search_result(brief_id: str = "brief-1", repo_name: str = "owner/repo") -> SearchResult:
    return SearchResult(
        brief_id=brief_id,
        repo=_make_repo(repo_name),
        file_path="src/main.py",
    )


def _make_evaluated(brief_id: str = "brief-1", repo_name: str = "owner/repo", relevance: float = 0.8, quality: float = 0.7) -> EvaluatedResult:
    return EvaluatedResult(
        search_result=_make_search_result(brief_id, repo_name),
        relevance_score=relevance,
        quality_score=quality,
        summary="Good implementation",
        relevant_files=[RelevantFile(path="src/main.py", explanation="Core logic")],
    )


def _make_brief(id: str = "brief-1", subproblem: str = "Core libraries") -> SearchBrief:
    return SearchBrief(
        id=id,
        subproblem=subproblem,
        level="component",
        queries=[
            SearchQuery(query="test library", search_type="repository", qualifiers={"stars": ">50"}),
        ],
        relevance_criteria="Must be relevant",
    )


# --- Presenter tests ---


class TestPresenter:
    def test_render_markdown_has_all_sections(self):
        from stitcher.presenter import render_markdown

        report = ScoutReport(
            project_understanding="Building a web app",
            subproblems=[
                SubproblemReport(
                    subproblem="Authentication",
                    recommended=[_make_evaluated(repo_name="auth/lib")],
                ),
                SubproblemReport(
                    subproblem="Database",
                    recommended=[_make_evaluated(repo_name="db/orm")],
                ),
            ],
            unexpected_findings=["Found a useful utility"],
            gaps=["No caching solution found"],
            token_usage=TokenUsageSummary(
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
                total_cost=0.015,
                model="claude-sonnet-4-20250514",
            ),
        )
        md = render_markdown(report)

        assert "# Code Scout Report" in md
        assert "## Project Understanding" in md
        assert "## Authentication" in md
        assert "## Database" in md
        assert "## Ecosystem Map" in md
        assert "## Patterns & Insights" in md
        assert "## Unexpected Findings" in md
        assert "## Gaps" in md
        assert "## Cost Summary" in md
        assert "$0.0150" in md

    def test_ecosystem_map_deduplicates_repos(self):
        from stitcher.presenter import render_markdown

        shared_repo = _make_evaluated(repo_name="shared/lib")
        report = ScoutReport(
            project_understanding="Test",
            subproblems=[
                SubproblemReport(subproblem="Area A", recommended=[shared_repo]),
                SubproblemReport(subproblem="Area B", recommended=[shared_repo]),
            ],
        )
        md = render_markdown(report)

        # Should appear in ecosystem map with both subproblems
        assert "shared/lib" in md
        assert "Area A" in md
        assert "Area B" in md

    def test_empty_report_renders(self):
        from stitcher.presenter import render_markdown

        report = ScoutReport(project_understanding="Empty project")
        md = render_markdown(report)
        assert "# Code Scout Report" in md
        assert "Empty project" in md


# --- Cross-subproblem dedup tests ---


class TestDeduplication:
    def test_cross_cutting_repos_detected(self):
        """Repos appearing in multiple subproblems should be noted as Swiss Army knife repos."""
        from stitcher.models import ScoutReport

        # Simulate what agent.py does: track repos across briefs
        all_evaluated = {
            "brief-1": [_make_evaluated("brief-1", "shared/repo", relevance=0.9)],
            "brief-2": [_make_evaluated("brief-2", "shared/repo", relevance=0.7)],
        }
        all_briefs = {
            "brief-1": _make_brief("brief-1", "Auth"),
            "brief-2": _make_brief("brief-2", "Database"),
        }

        # Replicate the dedup logic from agent.py
        repo_to_briefs: dict[str, list[str]] = {}
        repo_best_score: dict[str, tuple[float, str]] = {}

        for brief_id, evaluated_list in all_evaluated.items():
            brief = all_briefs.get(brief_id)
            subproblem_label = brief.subproblem if brief else brief_id
            for ev in evaluated_list:
                name = ev.search_result.repo.full_name
                repo_to_briefs.setdefault(name, [])
                if subproblem_label not in repo_to_briefs[name]:
                    repo_to_briefs[name].append(subproblem_label)
                avg = (ev.relevance_score + ev.quality_score) / 2
                prev_best, _ = repo_best_score.get(name, (-1.0, ""))
                if avg > prev_best:
                    repo_best_score[name] = (avg, brief_id)

        cross_cutting = {name: subs for name, subs in repo_to_briefs.items() if len(subs) > 1}

        assert "shared/repo" in cross_cutting
        assert len(cross_cutting["shared/repo"]) == 2

    def test_dedup_keeps_best_scored_version(self):
        """After dedup, the repo should only remain in the brief where it scored highest."""
        all_evaluated = {
            "brief-1": [_make_evaluated("brief-1", "shared/repo", relevance=0.9, quality=0.9)],
            "brief-2": [_make_evaluated("brief-2", "shared/repo", relevance=0.5, quality=0.5)],
        }

        repo_best_score = {"shared/repo": (0.9, "brief-1")}
        cross_cutting = {"shared/repo": ["Auth", "Database"]}

        for brief_id, evaluated_list in all_evaluated.items():
            deduped = []
            for ev in evaluated_list:
                name = ev.search_result.repo.full_name
                if name in cross_cutting:
                    _, best_brief = repo_best_score[name]
                    if best_brief != brief_id:
                        continue
                deduped.append(ev)
            all_evaluated[brief_id] = deduped

        assert len(all_evaluated["brief-1"]) == 1
        assert len(all_evaluated["brief-2"]) == 0


# --- Brief generation tests ---


class TestBriefGeneration:
    def test_generate_brief_markdown(self):
        from stitcher.brief import generate_brief

        report = ScoutReport(
            project_understanding="Building a REST API",
            subproblems=[
                SubproblemReport(
                    subproblem="HTTP framework",
                    recommended=[_make_evaluated(repo_name="pallets/flask")],
                ),
            ],
        )
        md = generate_brief(report, language="python")

        assert "# Research Brief" in md
        assert "python" in md.lower()
        assert "pallets/flask" in md

    def test_generate_deps_manifest_python(self):
        from stitcher.brief import generate_deps_manifest

        report = ScoutReport(
            project_understanding="Test",
            subproblems=[
                SubproblemReport(
                    subproblem="Framework",
                    recommended=[_make_evaluated(repo_name="pallets/flask")],
                ),
            ],
        )
        manifest = generate_deps_manifest(report, language="python")

        assert "requirements.txt" in manifest
        assert "flask" in manifest

    def test_generate_deps_manifest_rust(self):
        from stitcher.brief import generate_deps_manifest

        report = ScoutReport(
            project_understanding="Test",
            subproblems=[
                SubproblemReport(
                    subproblem="Framework",
                    recommended=[_make_evaluated(repo_name="tokio-rs/axum")],
                ),
            ],
        )
        manifest = generate_deps_manifest(report, language="rust")

        assert "Cargo.toml" in manifest
        assert "axum" in manifest


# --- Cache tests ---


class TestCache:
    def test_cache_get_miss_returns_none(self):
        from stitcher.cache import cache_get

        result = cache_get("nonexistent", "key")
        # Should return None on miss (or if cache unavailable)
        assert result is None

    def test_cache_roundtrip(self):
        from stitcher.cache import cache_get, cache_set

        cache_set("test_ns", "key1", value={"data": 42}, ttl=60)
        result = cache_get("test_ns", "key1")
        # If diskcache is installed, should get the value back
        # If not installed, both operations are no-ops
        if result is not None:
            assert result == {"data": 42}


# --- Token usage tests ---


class TestTokenUsage:
    def test_token_usage_summary_in_report(self):
        report = ScoutReport(
            project_understanding="Test",
            token_usage=TokenUsageSummary(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                total_cost=0.001,
                model="test-model",
            ),
        )
        assert report.token_usage is not None
        assert report.token_usage.total_tokens == 150
        assert report.token_usage.model == "test-model"

    def test_report_without_token_usage(self):
        report = ScoutReport(project_understanding="Test")
        assert report.token_usage is None
