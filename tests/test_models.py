"""Tests for data models."""

from __future__ import annotations

from stitcher.models import (
    EvaluatedResult,
    RelevantFile,
    RepoInfo,
    ScoutReport,
    SearchBrief,
    SearchQuery,
    SearchResult,
    SubproblemReport,
)


class TestModels:
    def test_repo_info_defaults(self):
        repo = RepoInfo(full_name="org/repo", url="https://github.com/org/repo")
        assert repo.stars == 0
        assert repo.forks == 0
        assert repo.quality_score == 0.0
        assert repo.topics == []

    def test_search_query(self):
        q = SearchQuery(query="midi parser", search_type="repository")
        assert q.qualifiers == {}

    def test_search_brief(self):
        brief = SearchBrief(
            id="sp-1",
            subproblem="MIDI parsing",
            level="component",
            queries=[SearchQuery(query="midi", search_type="repository")],
            relevance_criteria="Must parse MIDI files",
        )
        assert len(brief.queries) == 1

    def test_evaluated_result(self):
        repo = RepoInfo(full_name="org/repo", url="https://github.com/org/repo")
        sr = SearchResult(brief_id="sp-1", repo=repo)
        ev = EvaluatedResult(
            search_result=sr,
            relevance_score=0.8,
            quality_score=0.7,
            summary="Good repo",
            relevant_files=[RelevantFile(path="src/main.py", explanation="Entry point")],
        )
        assert ev.relevance_score == 0.8
        assert len(ev.relevant_files) == 1

    def test_scout_report(self):
        report = ScoutReport(
            project_understanding="Build a MIDI app",
            subproblems=[SubproblemReport(subproblem="MIDI parsing")],
            gaps=["No MIDI output library found"],
        )
        assert len(report.subproblems) == 1
        assert len(report.gaps) == 1
