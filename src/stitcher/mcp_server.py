"""MCP server — exposes stitcher's scout as a tool for Claude Code and other MCP clients."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "stitcher",
    instructions="GitHub Code Scout — search GitHub for real, working code relevant to your project",
)


def _report_to_dict(report) -> dict:
    """Convert a ScoutReport to a JSON-serialisable dict."""
    subproblems = []
    for sp in report.subproblems:
        recs = []
        for rec in sp.recommended:
            repo = rec.search_result.repo
            recs.append({
                "repo": repo.full_name,
                "url": repo.url,
                "description": repo.description,
                "stars": repo.stars,
                "forks": repo.forks,
                "language": repo.language,
                "relevance_score": rec.relevance_score,
                "quality_score": rec.quality_score,
                "repo_quality_score": repo.quality_score,
                "summary": rec.summary,
                "caveats": rec.caveats,
                "relevant_files": [
                    {
                        "path": rf.path,
                        "start_line": rf.start_line,
                        "end_line": rf.end_line,
                        "explanation": rf.explanation,
                    }
                    for rf in rec.relevant_files
                ],
            })
        subproblems.append({
            "subproblem": sp.subproblem,
            "recommended": recs,
        })

    return {
        "project_understanding": report.project_understanding,
        "subproblems": subproblems,
        "unexpected_findings": report.unexpected_findings,
        "gaps": report.gaps,
    }


def _write_report_file(markdown: str, description: str, output_dir: str) -> str:
    """Write the markdown report to a file and return the path."""
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    slug = description[:60].lower()
    slug = "".join(c if c.isalnum() or c in " -_" else "" for c in slug)
    slug = slug.strip().replace(" ", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"scout-report-{slug}-{timestamp}.md"
    path = base / filename

    path.write_text(markdown, encoding="utf-8")
    return str(path)


@mcp.tool()
async def scout(
    description: str,
    repo: str | None = None,
    mode: str = "fast",
    model: str | None = None,
    save_report: str | None = None,
    generate_brief: bool = False,
    brief_language: str | None = None,
) -> str:
    """Search GitHub for real, working code relevant to a project description.

    Decomposes the problem into sub-problems, searches GitHub for implementations,
    reads actual code to evaluate quality and relevance, and produces a structured
    report with recommended repositories and files.

    Args:
        description: What you want to build — describe the project or feature.
        repo: Optional path or GitHub URL to an existing repo for context.
        mode: Search mode — "fast" (no refinement) or "deep" (iterative refinement).
        model: LLM model to use (e.g. "gpt-4o", "claude-sonnet-4-20250514"). Uses default from config if not set.
        save_report: Directory to write a .md report file. If not provided, no file is written.
        generate_brief: When true, include a model-agnostic research brief and starter dependency manifest in the response.
        brief_language: Target language for the dependency manifest (e.g. "python", "rust", "javascript", "go"). Auto-detected if not set.

    Returns:
        JSON with structured results including sub-problems, recommended repos, scores, and relevant files.
        When generate_brief is true, also includes "research_brief" and "deps_manifest" fields.
    """
    from .agent import ScoutError, run_scout
    from .config import Settings
    from .presenter import render_markdown

    try:
        kwargs: dict = {"mode": mode}
        if model:
            kwargs["model"] = model
        settings = Settings(**kwargs)  # type: ignore[arg-type]
    except Exception as e:
        return json.dumps({"error": f"Configuration error: {e}"})

    try:
        report = await run_scout(description, repo, settings, progress=False)
    except ScoutError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Unexpected error: {e}"})

    result = _report_to_dict(report)

    # Only write file if explicitly requested
    if save_report:
        markdown = render_markdown(report)
        report_path = _write_report_file(markdown, description, save_report)
        result["report_file"] = report_path

    # Include research brief and deps manifest when requested
    if generate_brief:
        from .brief import generate_brief as _gen_brief
        from .brief import generate_deps_manifest, _detect_language

        lang = brief_language or _detect_language(report) or "python"
        result["research_brief"] = _gen_brief(report, language=lang)
        result["deps_manifest"] = generate_deps_manifest(report, language=lang)

    return json.dumps(result, indent=2)
