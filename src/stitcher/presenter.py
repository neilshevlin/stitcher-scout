"""Render a ScoutReport as markdown."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import EvaluatedResult, ScoutReport, SearchResult


def _quality_badge(score: float) -> str:
    """Return a text badge for a quality score."""
    if score >= 0.7:
        return "high"
    elif score >= 0.4:
        return "medium"
    else:
        return "low"


def _format_repo_signals(repo) -> str:
    """Format key repo signals as a compact line."""
    parts = []
    parts.append(f"★ {repo.stars:,}")
    if repo.forks:
        parts.append(f"🔀 {repo.forks:,}")
    if repo.contributors_count:
        parts.append(f"👥 {repo.contributors_count}")
    if repo.last_pushed:
        days = (datetime.now(timezone.utc) - repo.last_pushed).days
        if days <= 1:
            parts.append("pushed today")
        elif days <= 30:
            parts.append(f"pushed {days}d ago")
        elif days <= 365:
            parts.append(f"pushed {days // 30}mo ago")
        else:
            parts.append(f"pushed {days // 365}y ago")
    if repo.has_ci:
        parts.append("CI ✓")
    if repo.has_license:
        parts.append(f"License: {repo.license_name}")
    if repo.release_count:
        parts.append(f"{repo.release_count} releases")
    if repo.org_owned:
        parts.append("org-owned")
    return " | ".join(parts)


def render_markdown(report: ScoutReport) -> str:
    """Render a full ScoutReport to markdown string."""
    lines: list[str] = []
    lines.append("# Code Scout Report\n")

    lines.append("## Project Understanding\n")
    lines.append(report.project_understanding)
    lines.append("")

    for sp in report.subproblems:
        lines.append(f"## {sp.subproblem}\n")

        if not sp.recommended:
            lines.append("_No results found for this sub-problem._\n")
            continue

        for i, rec in enumerate(sp.recommended):
            repo = rec.search_result.repo
            label = "Recommended" if i == 0 else "Alternative"
            badge = _quality_badge(repo.quality_score)

            lines.append(f"### {label}: {repo.full_name} [{badge} quality]\n")

            if repo.description:
                lines.append(f"> {repo.description}\n")

            lines.append(f"- **Signals:** {_format_repo_signals(repo)}")
            lines.append(f"- **Link:** {repo.url}")

            for rf in rec.relevant_files:
                line_range = ""
                if rf.start_line and rf.end_line:
                    line_range = f", lines {rf.start_line}-{rf.end_line}"
                elif rf.start_line:
                    line_range = f", line {rf.start_line}+"
                lines.append(f"- **File:** `{rf.path}`{line_range}")
                lines.append(f"  - {rf.explanation}")

            lines.append(f"- **Summary:** {rec.summary}")

            if rec.caveats:
                lines.append(f"- **Caveats:** {rec.caveats}")

            lines.append(
                f"- **Relevance:** {rec.relevance_score:.1f} | "
                f"**Quality:** {rec.quality_score:.1f} | "
                f"**Repo score:** {repo.quality_score:.2f}"
            )
            lines.append("")

    if report.unexpected_findings:
        lines.append("## Unexpected Findings\n")
        for finding in report.unexpected_findings:
            lines.append(f"- {finding}")
        lines.append("")

    if report.gaps:
        lines.append("## Gaps\n")
        for gap in report.gaps:
            lines.append(f"- {gap}")
        lines.append("")

    return "\n".join(lines)


def render_search_results_simple(results: list[SearchResult], query: str) -> str:
    """Render raw search results as markdown (used in skeleton / pre-evaluation)."""
    lines: list[str] = []
    lines.append(f"# Code Scout Results\n")
    lines.append(f"**Query:** `{query}`\n")
    lines.append(f"**Results found:** {len(results)}\n")

    seen_repos: set[str] = set()
    for r in results:
        if r.repo.full_name in seen_repos:
            continue
        seen_repos.add(r.repo.full_name)

        signals = _format_repo_signals(r.repo)
        lines.append(f"### {r.repo.full_name}\n")

        if r.repo.description:
            lines.append(f"> {r.repo.description}\n")

        lines.append(f"- **Signals:** {signals}")
        lines.append(f"- **Link:** {r.repo.url}")
        if r.file_path:
            lines.append(f"- **File:** `{r.file_path}`")
        if r.repo.language:
            lines.append(f"- **Language:** {r.repo.language}")
        lines.append("")

    return "\n".join(lines)
