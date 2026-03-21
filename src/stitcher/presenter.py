"""Render a ScoutReport as markdown."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .models import ScoutReport, SearchResult


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
        days = max(0, (datetime.now(timezone.utc) - repo.last_pushed).days)
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

    # Ecosystem Map
    ecosystem_lines = _render_ecosystem_map(report)
    if ecosystem_lines:
        lines.extend(ecosystem_lines)

    # Patterns & Insights
    insight_lines = _render_insights(report)
    if insight_lines:
        lines.extend(insight_lines)

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

    if report.token_usage:
        tu = report.token_usage
        lines.append("## Cost Summary\n")
        lines.append(f"- **Model:** {tu.model}")
        lines.append(f"- **Prompt tokens:** {tu.prompt_tokens:,}")
        lines.append(f"- **Completion tokens:** {tu.completion_tokens:,}")
        lines.append(f"- **Total tokens:** {tu.total_tokens:,}")
        if tu.total_cost is None:
            lines.append("- **Estimated cost:** unavailable")
        else:
            lines.append(f"- **Estimated cost:** ${tu.total_cost:.4f}")
        lines.append("")

    return "\n".join(lines)


def _render_ecosystem_map(report: ScoutReport) -> list[str]:
    """Build an ecosystem map table of all unique repos across subproblems."""
    repo_data: dict[str, dict] = {}
    for sp in report.subproblems:
        for rec in sp.recommended:
            repo = rec.search_result.repo
            name = repo.full_name
            if name not in repo_data:
                repo_data[name] = {
                    "stars": repo.stars,
                    "language": repo.language or "Unknown",
                    "subproblems": set(),
                    "url": repo.url,
                }
            repo_data[name]["subproblems"].add(sp.subproblem)
            if repo.stars > repo_data[name]["stars"]:
                repo_data[name]["stars"] = repo.stars

    if not repo_data:
        return []

    sorted_repos = sorted(
        repo_data.items(),
        key=lambda item: (len(item[1]["subproblems"]), item[1]["stars"]),
        reverse=True,
    )

    lines: list[str] = []
    lines.append("## Ecosystem Map\n")
    lines.append("| Repository | Stars | Language | Relevant to |")
    lines.append("|---|---|---|---|")

    for name, data in sorted_repos:
        subs = ", ".join(sorted(data["subproblems"]))
        lines.append(
            f"| [{name}]({data['url']}) | {data['stars']:,} | {data['language']} | {subs} |"
        )

    lines.append("")
    return lines


def _render_insights(report: ScoutReport) -> list[str]:
    """Compute and render patterns & insights from the report data."""
    all_repos = []
    for sp in report.subproblems:
        for rec in sp.recommended:
            all_repos.append(rec.search_result.repo)

    if not all_repos:
        return []

    seen: set[str] = set()
    unique_repos = []
    for repo in all_repos:
        if repo.full_name not in seen:
            seen.add(repo.full_name)
            unique_repos.append(repo)

    lines: list[str] = []
    lines.append("## Patterns & Insights\n")

    lang_counts = Counter(r.language for r in unique_repos if r.language)
    if lang_counts:
        top_lang, top_count = lang_counts.most_common(1)[0]
        pct = top_count / len(unique_repos) * 100
        lines.append(f"- **Dominant language:** {top_lang} ({pct:.0f}% of repos)")

    all_topics = Counter()
    for repo in unique_repos:
        all_topics.update(repo.topics)
    if all_topics:
        top_topics = [t for t, _ in all_topics.most_common(5)]
        lines.append(f"- **Common topics:** {', '.join(top_topics)}")

    license_counts = Counter()
    for repo in unique_repos:
        if repo.license_name:
            license_counts[repo.license_name] += 1
    if license_counts:
        total_licensed = sum(license_counts.values())
        parts = []
        for lic, count in license_counts.most_common():
            pct = count / total_licensed * 100
            parts.append(f"{pct:.0f}% {lic}")
        lines.append(f"- **License distribution:** {', '.join(parts)}")

    now = datetime.now(timezone.utc)
    ages_days = []
    activity_days = []
    for repo in unique_repos:
        if repo.created_at:
            ages_days.append(max(0, (now - repo.created_at).days))
        if repo.last_pushed:
            activity_days.append(max(0, (now - repo.last_pushed).days))

    if ages_days:
        avg_age = sum(ages_days) / len(ages_days)
        if avg_age >= 365:
            lines.append(f"- **Average repo age:** {avg_age / 365:.1f} years")
        else:
            lines.append(f"- **Average repo age:** {avg_age:.0f} days")

    if activity_days:
        avg_activity = sum(activity_days) / len(activity_days)
        if avg_activity <= 7:
            activity_label = "very active (avg last push within a week)"
        elif avg_activity <= 30:
            activity_label = "active (avg last push within a month)"
        elif avg_activity <= 180:
            activity_label = "moderate (avg last push within 6 months)"
        else:
            activity_label = f"low (avg last push {avg_activity:.0f} days ago)"
        lines.append(f"- **Activity level:** {activity_label}")

    lines.append("")
    return lines


def render_search_results_simple(results: list[SearchResult], query: str) -> str:
    """Render raw search results as markdown (used in skeleton / pre-evaluation)."""
    lines: list[str] = []
    lines.append("# Code Scout Results\n")
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
