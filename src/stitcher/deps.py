"""Dependency graph following — extract deps from top results and search for them.

After finding good code, read their dependency manifests to discover the libraries
that experienced practitioners trust. These libraries often contain the real
implementation gems.
"""

from __future__ import annotations

import asyncio
import re

from .github_client import GitHubClient
from .models import EvaluatedResult, SearchBrief, SearchQuery

# Manifest files and how to extract dependency names from them
_MANIFEST_PATTERNS: dict[str, tuple[str, re.Pattern]] = {
    "Cargo.toml": ("rust", re.compile(r'^([a-zA-Z0-9_-]+)\s*=', re.MULTILINE)),
    "requirements.txt": ("python", re.compile(r'^([a-zA-Z0-9_-]+)', re.MULTILINE)),
    "pyproject.toml": ("python", re.compile(r'"([a-zA-Z0-9_-]+)(?:[><=~!]|$)', re.MULTILINE)),
    "package.json": ("javascript", re.compile(r'"([a-zA-Z0-9@/_-]+)":\s*"', re.MULTILINE)),
    "go.mod": ("go", re.compile(r'^\s+([\w./]+)\s+v', re.MULTILINE)),
}

# Common deps to ignore (they're too generic to search for)
_IGNORE_DEPS = {
    # Rust
    "serde", "serde_json", "tokio", "anyhow", "thiserror", "log", "env_logger",
    "clap", "rand", "chrono", "regex", "lazy_static", "once_cell", "tracing",
    "futures", "async-trait",
    # Python
    "pytest", "setuptools", "wheel", "pip", "black", "flake8", "mypy",
    "typing-extensions", "importlib-metadata", "six", "certifi", "urllib3",
    "requests", "numpy", "pandas",
    # JS
    "typescript", "eslint", "prettier", "jest", "mocha",
    # Go
    "golang.org/x/sys", "golang.org/x/text", "golang.org/x/net",
}


async def extract_deps_from_results(
    evaluated: dict[str, list[EvaluatedResult]],
    gh: GitHubClient,
    max_repos: int = 5,
) -> list[str]:
    """Extract dependency names from the top-scored repos' manifests.

    Returns a list of library/package names that are worth searching for.
    """
    # Collect top repos across all sub-problems
    all_results: list[EvaluatedResult] = []
    for results in evaluated.values():
        all_results.extend(results)

    # Sort by combined score, take top N unique repos
    all_results.sort(key=lambda r: (r.relevance_score + r.quality_score) / 2, reverse=True)
    seen_repos: set[str] = set()
    top_repos: list[str] = []
    for r in all_results:
        repo = r.search_result.repo.full_name
        if repo not in seen_repos:
            seen_repos.add(repo)
            top_repos.append(repo)
        if len(top_repos) >= max_repos:
            break

    # Fetch manifests and extract deps
    semaphore = asyncio.Semaphore(5)
    all_deps: set[str] = set()

    async def _fetch_deps(repo_name: str) -> set[str]:
        deps: set[str] = set()
        async with semaphore:
            for manifest, (lang, pattern) in _MANIFEST_PATTERNS.items():
                try:
                    content = await gh.get_file_content(repo_name, manifest, max_lines=200)
                    matches = pattern.findall(content)
                    for dep in matches:
                        dep_clean = dep.strip().lower().split("[")[0]  # Remove extras like [features]
                        if dep_clean and dep_clean not in _IGNORE_DEPS and len(dep_clean) >= 2:
                            deps.add(dep_clean)
                    break  # Found a manifest, don't look for others
                except Exception:
                    continue
        return deps

    results = await asyncio.gather(*[_fetch_deps(repo) for repo in top_repos])
    for dep_set in results:
        all_deps.update(dep_set)

    return list(all_deps)


def create_dep_search_brief(deps: list[str], language: str | None = None) -> SearchBrief | None:
    """Create a SearchBrief to search for discovered dependencies as libraries.

    Returns None if no meaningful deps were found.
    """
    if not deps:
        return None

    # Take the most interesting-looking deps (skip single-char, very common ones)
    interesting = [d for d in deps if len(d) >= 3][:15]
    if not interesting:
        return None

    queries: list[SearchQuery] = []

    # Search for each dep as a standalone repo
    for dep in interesting[:8]:
        qualifiers: dict[str, str] = {"stars": ">10"}
        if language:
            qualifiers["language"] = language
        queries.append(SearchQuery(
            query=dep,
            search_type="repository",
            qualifiers=qualifiers,
        ))

    # Also search for deps in combination
    if len(interesting) >= 2:
        queries.append(SearchQuery(
            query=f"{interesting[0]} {interesting[1]}",
            search_type="repository",
            qualifiers={"stars": ">20"},
        ))

    return SearchBrief(
        id="deps-discovered",
        subproblem="Libraries discovered from dependency analysis of top results",
        level="component",
        queries=queries,
        relevance_criteria="Must be a standalone library/package that provides reusable functionality",
    )
