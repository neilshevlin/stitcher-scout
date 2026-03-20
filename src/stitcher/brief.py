"""Generate model-agnostic research briefs and dependency manifests from scout results."""

from __future__ import annotations

from .models import ScoutReport, SubproblemReport


# ---------------------------------------------------------------------------
# Language detection helpers
# ---------------------------------------------------------------------------

_LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python",
    "python": "python",
    "rs": "rust",
    "rust": "rust",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "javascript",  # npm/package.json ecosystem
    "go": "go",
    "golang": "go",
}


def _detect_language(report: ScoutReport) -> str | None:
    """Best-effort language detection from the repos in a report."""
    counts: dict[str, int] = {}
    for sp in report.subproblems:
        for rec in sp.recommended:
            lang = rec.search_result.repo.language
            if lang:
                key = lang.lower()
                counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    dominant = max(counts, key=lambda k: counts[k])
    return _LANGUAGE_ALIASES.get(dominant, dominant)


# ---------------------------------------------------------------------------
# Library extraction
# ---------------------------------------------------------------------------

def _extract_libraries(report: ScoutReport) -> list[dict[str, str]]:
    """Extract library names and purposes from evaluated results.

    Returns a list of dicts with keys: name, purpose, source_repo.
    Only libraries that appear in positively-scored recommendations are included.
    """
    libs: dict[str, dict[str, str]] = {}
    for sp in report.subproblems:
        for rec in sp.recommended:
            if rec.relevance_score < 0.3:
                continue
            repo = rec.search_result.repo
            # Use the repo name (last segment) as a candidate library name
            name = repo.full_name.split("/")[-1]
            if name not in libs:
                libs[name] = {
                    "name": name,
                    "purpose": sp.subproblem,
                    "source_repo": repo.full_name,
                    "description": repo.description or "",
                }
    return list(libs.values())


# ---------------------------------------------------------------------------
# GitHub URL helpers
# ---------------------------------------------------------------------------

def _github_file_url(repo_full_name: str, file_path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Build a GitHub URL pointing to a specific file (and optionally line range)."""
    url = f"https://github.com/{repo_full_name}/blob/HEAD/{file_path}"
    if start_line and end_line:
        url += f"#L{start_line}-L{end_line}"
    elif start_line:
        url += f"#L{start_line}"
    return url


# ---------------------------------------------------------------------------
# Research brief generation
# ---------------------------------------------------------------------------

def _render_subproblem_section(sp: SubproblemReport) -> list[str]:
    """Render one sub-problem section of the research brief."""
    lines: list[str] = []
    lines.append(f"### {sp.subproblem}\n")

    if not sp.recommended:
        lines.append("No repositories found for this sub-problem.\n")
        return lines

    # Recommended approach — use the top result's summary
    top = sp.recommended[0]
    lines.append("**Recommended approach**\n")
    lines.append(f"{top.summary}\n")

    # Key libraries with install context
    lines.append("**Key libraries**\n")
    for rec in sp.recommended:
        repo = rec.search_result.repo
        name = repo.full_name.split("/")[-1]
        lang = (repo.language or "").lower()
        install = _install_hint(name, lang)
        desc_part = f" — {repo.description}" if repo.description else ""
        lines.append(f"- **{repo.full_name}**{desc_part}")
        if install:
            lines.append(f"  - Install: `{install}`")
        lines.append(f"  - {repo.url}")

    lines.append("")

    # Specific files to study
    has_files = any(rec.relevant_files for rec in sp.recommended)
    if has_files:
        lines.append("**Files to study**\n")
        for rec in sp.recommended:
            repo = rec.search_result.repo
            for rf in rec.relevant_files:
                url = _github_file_url(repo.full_name, rf.path, rf.start_line, rf.end_line)
                lines.append(f"- [`{repo.full_name}/{rf.path}`]({url})")
                lines.append(f"  - {rf.explanation}")
        lines.append("")

    # Caveats
    caveats = [rec.caveats for rec in sp.recommended if rec.caveats]
    if caveats:
        lines.append("**Caveats**\n")
        for c in caveats:
            lines.append(f"- {c}")
        lines.append("")

    return lines


def _install_hint(package_name: str, language: str) -> str:
    """Return a short install command for a package, or empty string."""
    lang = language.lower() if language else ""
    if lang in ("python", "py"):
        return f"pip install {package_name}"
    if lang in ("rust", "rs"):
        return f"cargo add {package_name}"
    if lang in ("javascript", "typescript", "js", "ts"):
        return f"npm install {package_name}"
    if lang in ("go", "golang"):
        return f"go get {package_name}"
    return ""


def generate_brief(report: ScoutReport, language: str | None = None) -> str:
    """Generate a model-agnostic research brief from scout results.

    The brief is a structured markdown document designed to be consumed by any
    developer or AI agent.  It contains: project understanding, per-subproblem
    recommendations (libraries, files, caveats), dependency decisions,
    architecture notes, and gaps/risks.

    Args:
        report: The ScoutReport produced by a scout run.
        language: Optional target language hint (e.g. "python", "rust").
                  If *None*, the dominant language across results is used.

    Returns:
        A markdown string.
    """
    resolved_lang = language or _detect_language(report) or "unknown"
    lines: list[str] = []

    # -- Header --
    lines.append("# Research Brief\n")
    lines.append(f"Target language: **{resolved_lang}**\n")

    # -- Project understanding --
    lines.append("## Project Understanding\n")
    lines.append(report.project_understanding)
    lines.append("")

    # -- Per-subproblem sections --
    lines.append("## Sub-problems and Recommendations\n")
    for sp in report.subproblems:
        lines.extend(_render_subproblem_section(sp))

    # -- Dependency recommendations --
    libs = _extract_libraries(report)
    if libs:
        lines.append("## Dependency Recommendations\n")
        lines.append("Concrete library choices derived from scout results:\n")
        for lib in libs:
            lines.append(f"- **Use** `{lib['name']}` **for** {lib['purpose']}")
            if lib["description"]:
                lines.append(f"  - {lib['description']}")
            lines.append(f"  - Source: {lib['source_repo']}")
        lines.append("")

    # -- Architecture notes --
    # Gather patterns observed across top repos
    patterns: list[str] = []
    languages_seen: set[str] = set()
    topic_counts: dict[str, int] = {}
    for sp in report.subproblems:
        for rec in sp.recommended:
            repo = rec.search_result.repo
            if repo.language:
                languages_seen.add(repo.language)
            for t in repo.topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1

    if languages_seen:
        patterns.append(f"Languages encountered: {', '.join(sorted(languages_seen))}")
    top_topics = sorted(topic_counts, key=lambda t: topic_counts[t], reverse=True)[:10]
    if top_topics:
        patterns.append(f"Common topics/tags: {', '.join(top_topics)}")

    # Licence observations
    license_names: set[str] = set()
    for sp in report.subproblems:
        for rec in sp.recommended:
            repo = rec.search_result.repo
            if repo.license_name:
                license_names.add(repo.license_name)
    if license_names:
        patterns.append(f"Licences observed: {', '.join(sorted(license_names))}")

    if patterns:
        lines.append("## Architecture Notes\n")
        lines.append("Patterns observed across the top-ranked repositories:\n")
        for p in patterns:
            lines.append(f"- {p}")
        lines.append("")

    if report.unexpected_findings:
        lines.append("### Unexpected Findings\n")
        for f in report.unexpected_findings:
            lines.append(f"- {f}")
        lines.append("")

    # -- Gaps and risks --
    lines.append("## Gaps and Risks\n")
    if report.gaps:
        for gap in report.gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("- No significant gaps identified by the scout run.")
    lines.append("")

    # Check for subproblems with no results — that is a risk
    empty = [sp.subproblem for sp in report.subproblems if not sp.recommended]
    if empty:
        lines.append("Sub-problems with **no results** (you may need to build from scratch):\n")
        for e in empty:
            lines.append(f"- {e}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dependency manifest generation
# ---------------------------------------------------------------------------

def generate_deps_manifest(report: ScoutReport, language: str) -> str:
    """Generate a starter dependency manifest from scout results.

    Extracts library names from positively-evaluated scout results and formats
    them as a dependency snippet for the given language ecosystem.

    Supported languages: python, rust, javascript, go.

    Args:
        report: The ScoutReport produced by a scout run.
        language: Target language (e.g. "python", "rust", "javascript", "go").

    Returns:
        A string containing the dependency manifest snippet.
    """
    lang = _LANGUAGE_ALIASES.get(language.lower(), language.lower())
    libs = _extract_libraries(report)

    if not libs:
        return f"# No dependencies extracted from scout results (language: {lang})\n"

    formatter = _MANIFEST_FORMATTERS.get(lang, _format_generic)
    return formatter(libs)


def _format_python(libs: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("# requirements.txt — generated from scout results")
    lines.append("# Verify versions before using in production.\n")
    for lib in libs:
        lines.append(lib["name"])
    lines.append("")
    lines.append("# --- pyproject.toml alternative ---")
    lines.append("# [project]")
    lines.append("# dependencies = [")
    for lib in libs:
        lines.append(f'#     "{lib["name"]}",')
    lines.append("# ]")
    lines.append("")
    return "\n".join(lines)


def _format_rust(libs: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("# Cargo.toml — generated from scout results")
    lines.append("# Verify crate names and versions on crates.io before using.\n")
    lines.append("[dependencies]")
    for lib in libs:
        # Use wildcard version; user should pin
        lines.append(f'{lib["name"]} = "*"  # {lib["purpose"]}')
    lines.append("")
    return "\n".join(lines)


def _format_javascript(libs: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("{")
    lines.append('  "dependencies": {')
    entries = []
    for lib in libs:
        entries.append(f'    "{lib["name"]}": "*"')
    lines.append(",\n".join(entries))
    lines.append("  }")
    lines.append("}")
    lines.append("")
    lines.append("// package.json snippet — generated from scout results")
    lines.append("// Verify package names on npmjs.com and pin versions before using.")
    lines.append("")
    return "\n".join(lines)


def _format_go(libs: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("// go.mod snippet — generated from scout results")
    lines.append("// Verify module paths and versions before using.\n")
    lines.append("require (")
    for lib in libs:
        # Go modules typically use the full repo path
        module_path = f"github.com/{lib['source_repo']}"
        lines.append(f"\t{module_path} v0.0.0 // {lib['purpose']}")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def _format_generic(libs: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("# Dependencies — generated from scout results")
    lines.append("# Language-specific manifest format not available; listing libraries.\n")
    for lib in libs:
        lines.append(f"- {lib['name']}  # {lib['purpose']} (from {lib['source_repo']})")
    lines.append("")
    return "\n".join(lines)


_MANIFEST_FORMATTERS: dict[str, callable] = {
    "python": _format_python,
    "rust": _format_rust,
    "javascript": _format_javascript,
    "go": _format_go,
}
