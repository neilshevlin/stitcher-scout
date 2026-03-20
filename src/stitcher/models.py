"""Data models that flow between components."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# --- Search inputs ---


class SearchQuery(BaseModel):
    """A single query to run against the GitHub API."""

    query: str
    search_type: Literal["code", "repository", "topic"]
    qualifiers: dict[str, str] = {}


class SearchBrief(BaseModel):
    """A sub-problem with its search queries, produced by the decomposer."""

    id: str
    subproblem: str
    level: Literal["architecture", "component", "pattern"]
    queries: list[SearchQuery]
    relevance_criteria: str


# --- Search results ---


class RepoInfo(BaseModel):
    """Metadata about a GitHub repository."""

    full_name: str
    url: str
    description: str | None = None
    stars: int = 0
    forks: int = 0
    last_pushed: datetime | None = None
    created_at: datetime | None = None
    archived: bool = False
    language: str | None = None
    topics: list[str] = []

    # Quality signals (populated by enrich_repo)
    contributors_count: int = 0
    has_ci: bool = False
    has_license: bool = False
    license_name: str | None = None
    org_owned: bool = False
    release_count: int = 0
    open_issues_count: int = 0

    # Computed score (populated by scoring.py)
    quality_score: float = 0.0


class SearchResult(BaseModel):
    """A single result from a GitHub search."""

    brief_id: str
    repo: RepoInfo
    file_path: str | None = None
    matched_text: str | None = None


# --- Evaluation ---


class RelevantFile(BaseModel):
    """A specific file/line-range that is relevant to the sub-problem."""

    path: str
    start_line: int | None = None
    end_line: int | None = None
    explanation: str


class EvaluatedResult(BaseModel):
    """A search result that has been evaluated by the LLM."""

    search_result: SearchResult
    relevance_score: float
    quality_score: float
    summary: str
    relevant_files: list[RelevantFile] = []
    caveats: str | None = None


# --- Refinement ---


class RefinementResult(BaseModel):
    """Output of the refinement step."""

    gaps: list[str] = []
    new_briefs: list[SearchBrief] = []
    observations: list[str] = []
    should_continue: bool = False


# --- Project context ---


class ProjectContext(BaseModel):
    """Parsed context about the user's project."""

    description: str
    language: str | None = None
    dependencies: list[str] = []
    framework: str | None = None
    repo_path: str | None = None


# --- Final report ---


class SubproblemReport(BaseModel):
    """Report section for a single sub-problem."""

    subproblem: str
    search_briefs_used: list[str] = []
    recommended: list[EvaluatedResult] = []


class ScoutReport(BaseModel):
    """The complete output report."""

    project_understanding: str
    subproblems: list[SubproblemReport] = []
    unexpected_findings: list[str] = []
    gaps: list[str] = []
