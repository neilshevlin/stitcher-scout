"""Parse project context from a local repo or GitHub URL."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .github_client import GitHubClient
from .models import ProjectContext


def _parse_pyproject(content: str) -> tuple[str | None, list[str]]:
    """Extract language and dependencies from pyproject.toml."""
    deps: list[str] = []
    in_deps = False
    for line in content.splitlines():
        if line.strip().startswith("dependencies"):
            in_deps = True
            continue
        if in_deps:
            if line.strip() == "]":
                in_deps = False
                continue
            # Extract package name from dependency string
            match = re.match(r'\s*"([a-zA-Z0-9_-]+)', line)
            if match:
                deps.append(match.group(1))
    return "python", deps


def _parse_package_json(content: str) -> tuple[str | None, list[str]]:
    """Extract language and dependencies from package.json."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return "javascript", []
    deps = list(data.get("dependencies", {}).keys())
    # Detect TypeScript
    dev_deps = data.get("devDependencies", {})
    lang = "typescript" if "typescript" in dev_deps else "javascript"
    return lang, deps


def _parse_go_mod(content: str) -> tuple[str | None, list[str]]:
    """Extract language and dependencies from go.mod."""
    deps: list[str] = []
    in_require = False
    for line in content.splitlines():
        if line.strip().startswith("require"):
            in_require = True
            continue
        if in_require:
            if line.strip() == ")":
                in_require = False
                continue
            parts = line.strip().split()
            if parts:
                deps.append(parts[0])
    return "go", deps


def _parse_cargo_toml(content: str) -> tuple[str | None, list[str]]:
    """Extract language and dependencies from Cargo.toml."""
    deps: list[str] = []
    in_deps = False
    for line in content.splitlines():
        if line.strip() == "[dependencies]":
            in_deps = True
            continue
        if in_deps:
            if line.strip().startswith("["):
                in_deps = False
                continue
            match = re.match(r"([a-zA-Z0-9_-]+)\s*=", line)
            if match:
                deps.append(match.group(1))
    return "rust", deps


MANIFEST_PARSERS = {
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
    "go.mod": _parse_go_mod,
    "Cargo.toml": _parse_cargo_toml,
}


async def parse_project_context(
    description: str,
    repo_path: str | None = None,
    gh: GitHubClient | None = None,
) -> ProjectContext:
    """Build a ProjectContext from the description and optional repo."""
    context = ProjectContext(description=description, repo_path=repo_path)

    if not repo_path:
        return context

    # Try local path first
    local = Path(repo_path)
    if local.is_dir():
        for manifest, parser in MANIFEST_PARSERS.items():
            manifest_path = local / manifest
            if manifest_path.exists():
                content = manifest_path.read_text()
                lang, deps = parser(content)
                context.language = lang
                context.dependencies = deps
                break
        return context

    # Try GitHub URL
    match = re.match(r"https?://github\.com/([^/]+/[^/]+)", repo_path)
    if match and gh:
        full_name = match.group(1).rstrip("/")
        for manifest, parser in MANIFEST_PARSERS.items():
            try:
                content = await gh.get_file_content(full_name, manifest)
                lang, deps = parser(content)
                context.language = lang
                context.dependencies = deps
                break
            except Exception:
                continue

    return context
