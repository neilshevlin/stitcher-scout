"""Tests for MCP server setup."""

from __future__ import annotations

from stitcher.mcp_server import mcp, _report_to_dict
from stitcher.models import (
    EvaluatedResult,
    RelevantFile,
    RepoInfo,
    ScoutReport,
    SearchResult,
    SubproblemReport,
)


class TestMCPServer:
    def test_server_has_scout_tool(self):
        # FastMCP registers tools — verify scout is registered
        tools = mcp._tool_manager._tools
        assert "scout" in tools

    def test_server_name(self):
        assert mcp.name == "stitcher"


class TestReportToDict:
    def test_empty_report(self):
        report = ScoutReport(project_understanding="Test", subproblems=[], gaps=[])
        result = _report_to_dict(report)
        assert result["project_understanding"] == "Test"
        assert result["subproblems"] == []
        assert result["gaps"] == []

    def test_full_report(self):
        repo = RepoInfo(full_name="org/repo", url="https://github.com/org/repo", stars=100, language="Python")
        sr = SearchResult(brief_id="sp-1", repo=repo)
        ev = EvaluatedResult(
            search_result=sr,
            relevance_score=0.9,
            quality_score=0.8,
            summary="Great repo",
            caveats="Needs Python 3.12",
            relevant_files=[RelevantFile(path="src/main.py", start_line=1, end_line=50, explanation="Core logic")],
        )
        report = ScoutReport(
            project_understanding="Build something",
            subproblems=[SubproblemReport(subproblem="Core", recommended=[ev])],
            unexpected_findings=["Found a cool thing"],
            gaps=["Missing X"],
        )
        result = _report_to_dict(report)
        assert len(result["subproblems"]) == 1
        rec = result["subproblems"][0]["recommended"][0]
        assert rec["repo"] == "org/repo"
        assert rec["stars"] == 100
        assert rec["relevance_score"] == 0.9
        assert rec["relevant_files"][0]["path"] == "src/main.py"
