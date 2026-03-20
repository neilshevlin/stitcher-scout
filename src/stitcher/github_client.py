"""Async GitHub API client using httpx."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime

import httpx

from .cache import (
    TTL_FILE_CONTENT,
    TTL_REPO_META,
    TTL_SEARCH,
    cache_get,
    cache_set,
)
from .models import RepoInfo, SearchResult


class GitHubClient:
    """Thin wrapper around the GitHub REST API."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._search_remaining: int | None = None

    async def close(self) -> None:
        await self._client.aclose()

    # --- Rate limit helpers ---

    def _update_rate_limit(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            self._search_remaining = int(remaining)

    async def _throttle_if_needed(self) -> None:
        if self._search_remaining is not None and self._search_remaining < 3:
            await asyncio.sleep(2.0)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        await self._throttle_if_needed()
        response = await self._client.request(method, url, **kwargs)
        self._update_rate_limit(response)

        if response.status_code == 401:
            raise httpx.HTTPStatusError(
                "GitHub token is invalid or expired. Check your GITHUB_TOKEN.",
                request=response.request,
                response=response,
            )

        if response.status_code == 403:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                await asyncio.sleep(float(retry_after))
                response = await self._client.request(method, url, **kwargs)
                self._update_rate_limit(response)

        response.raise_for_status()
        return response

    async def _request_safe(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        """Like _request but returns None on 404/403 instead of raising."""
        try:
            return await self._request(method, url, **kwargs)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 403, 409, 451):
                return None
            raise

    # --- Repo metadata ---

    def _parse_repo(self, data: dict) -> RepoInfo:
        pushed_at = data.get("pushed_at")
        created_at = data.get("created_at")
        license_data = data.get("license") or {}
        owner_data = data.get("owner") or {}

        return RepoInfo(
            full_name=data["full_name"],
            url=data["html_url"],
            description=data.get("description"),
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            last_pushed=datetime.fromisoformat(pushed_at.replace("Z", "+00:00")) if pushed_at else None,
            created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None,
            archived=data.get("archived", False),
            language=data.get("language"),
            topics=data.get("topics", []),
            has_license=license_data.get("spdx_id") not in (None, "NOASSERTION"),
            license_name=license_data.get("spdx_id"),
            org_owned=owner_data.get("type") == "Organization",
            open_issues_count=data.get("open_issues_count", 0),
        )

    async def get_repo_info(self, full_name: str) -> RepoInfo:
        resp = await self._request("GET", f"/repos/{full_name}")
        return self._parse_repo(resp.json())

    async def enrich_repo(self, repo: RepoInfo) -> RepoInfo:
        """Fetch additional quality signals for a repo: contributors, releases, CI presence."""
        cached = cache_get("enrich_repo", repo.full_name)
        if cached is not None:
            repo.contributors_count = cached["contributors_count"]
            repo.release_count = cached["release_count"]
            repo.has_ci = cached["has_ci"]
            return repo

        contributors, releases, has_ci = await asyncio.gather(
            self._get_contributors_count(repo.full_name),
            self._get_release_count(repo.full_name),
            self._check_ci_presence(repo.full_name),
        )
        repo.contributors_count = contributors
        repo.release_count = releases
        repo.has_ci = has_ci

        cache_set(
            "enrich_repo", repo.full_name,
            value={"contributors_count": contributors, "release_count": releases, "has_ci": has_ci},
            ttl=TTL_REPO_META,
        )
        return repo

    async def _get_contributors_count(self, full_name: str) -> int:
        """Get contributor count (capped at 30 per page, use anon=true for speed)."""
        resp = await self._request_safe("GET", f"/repos/{full_name}/contributors", params={"per_page": 1, "anon": "false"})
        if resp is None:
            return 0
        # GitHub returns the total in the Link header for pagination
        link = resp.headers.get("link", "")
        if 'rel="last"' in link:
            # Parse last page number from: <...?page=42>; rel="last"
            import re
            match = re.search(r'[&?]page=(\d+)>;\s*rel="last"', link)
            if match:
                return int(match.group(1))
        # No pagination = all results fit in one page
        data = resp.json()
        return len(data) if isinstance(data, list) else 0

    async def _get_release_count(self, full_name: str) -> int:
        """Get number of releases (check first page only)."""
        resp = await self._request_safe("GET", f"/repos/{full_name}/releases", params={"per_page": 5})
        if resp is None:
            return 0
        data = resp.json()
        return len(data) if isinstance(data, list) else 0

    async def _check_ci_presence(self, full_name: str) -> bool:
        """Check if the repo has CI/CD configuration."""
        # Check .github/workflows first (most common)
        resp = await self._request_safe("GET", f"/repos/{full_name}/contents/.github/workflows")
        if resp is not None:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return True

        # Check for other CI files
        for ci_path in ("Jenkinsfile", ".travis.yml", ".circleci/config.yml", ".gitlab-ci.yml"):
            resp = await self._request_safe("GET", f"/repos/{full_name}/contents/{ci_path}")
            if resp is not None:
                return True

        return False

    # --- Search ---

    async def search_code(
        self, query: str, qualifiers: dict[str, str] | None = None, per_page: int = 10
    ) -> list[SearchResult]:
        q = query
        for key, val in (qualifiers or {}).items():
            q += f" {key}:{val}"

        resp = await self._request("GET", "/search/code", params={"q": q, "per_page": per_page})
        items = resp.json().get("items", [])

        results: list[SearchResult] = []
        for item in items:
            repo_data = item.get("repository", {})
            results.append(
                SearchResult(
                    brief_id="skeleton",
                    repo=RepoInfo(
                        full_name=repo_data.get("full_name", ""),
                        url=repo_data.get("html_url", ""),
                        description=repo_data.get("description"),
                        stars=repo_data.get("stargazers_count", 0),
                        forks=repo_data.get("forks_count", 0),
                        archived=repo_data.get("archived", False),
                        language=None,
                        topics=[],
                    ),
                    file_path=item.get("path"),
                    matched_text=item.get("name"),
                )
            )
        return results

    async def search_repos(
        self, query: str, qualifiers: dict[str, str] | None = None, per_page: int = 10,
        sort: str | None = "stars", order: str = "desc",
    ) -> list[SearchResult]:
        q = query
        quals = dict(qualifiers or {})
        # Extract sort from qualifiers if the LLM put it there
        if "sort" in quals:
            sort = quals.pop("sort")
        for key, val in quals.items():
            q += f" {key}:{val}"

        cache_key_parts = [q, str(per_page), str(sort), order]
        cached = cache_get("search_repos", *cache_key_parts)
        if cached is not None:
            return cached

        params: dict = {"q": q, "per_page": per_page}
        if sort:
            params["sort"] = sort
            params["order"] = order

        resp = await self._request("GET", "/search/repositories", params=params)
        items = resp.json().get("items", [])

        results: list[SearchResult] = []
        for item in items:
            results.append(
                SearchResult(
                    brief_id="skeleton",
                    repo=self._parse_repo(item),
                )
            )

        cache_set("search_repos", *cache_key_parts, value=results, ttl=TTL_SEARCH)
        return results

    # --- File content ---

    async def get_file_content(self, full_name: str, path: str, max_lines: int = 500) -> str:
        cached = cache_get("file_content", full_name, path, str(max_lines))
        if cached is not None:
            return cached

        resp = await self._request("GET", f"/repos/{full_name}/contents/{path}")
        data = resp.json()

        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        else:
            content = data.get("content", "")

        lines = content.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines.append(f"\n... truncated at {max_lines} lines ...")
        result = "\n".join(lines)

        cache_set("file_content", full_name, path, str(max_lines), value=result, ttl=TTL_FILE_CONTENT)
        return result

    async def get_directory_tree(self, full_name: str, path: str = "") -> list[str]:
        resp = await self._request("GET", f"/repos/{full_name}/contents/{path}")
        data = resp.json()
        if not isinstance(data, list):
            return [data.get("path", "")]
        return [item["path"] for item in data]
