"""Disk cache for GitHub API responses using diskcache (SQLite-backed).

Gracefully degrades to no-op if diskcache is not installed.
Install with: pip install stitcher-scout[cache]
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

# TTL constants (in seconds)
TTL_SEARCH = 3600          # 1 hour for search results
TTL_REPO_META = 86400      # 24 hours for repo metadata / enrichment
TTL_FILE_CONTENT = 604800  # 7 days for file content

CACHE_DIR = Path(os.environ.get("STITCHER_CACHE_DIR", "~/.cache/stitcher-scout")).expanduser()

try:
    import diskcache

    _cache: diskcache.Cache | None = diskcache.Cache(str(CACHE_DIR))
except Exception:
    _cache = None


def _make_key(namespace: str, *parts: str) -> str:
    """Build a deterministic cache key from a namespace and variable parts."""
    raw = json.dumps([namespace, *parts], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(namespace: str, *parts: str) -> Any | None:
    """Retrieve a value from the cache, or None on miss / if caching is unavailable."""
    if _cache is None:
        return None
    key = _make_key(namespace, *parts)
    sentinel = object()
    val = _cache.get(key, default=sentinel)
    if val is sentinel:
        return None
    return val


def cache_set(namespace: str, *parts: str, value: Any, ttl: int) -> None:
    """Store a value in the cache with the given TTL (seconds)."""
    if _cache is None:
        return
    key = _make_key(namespace, *parts)
    _cache.set(key, value, expire=ttl)


def clear_cache() -> int:
    """Clear the entire disk cache. Returns bytes freed (approximate)."""
    if _cache is not None:
        size = int(getattr(_cache, "volume", lambda: 0)())
        _cache.clear()
        return size

    # Fallback: just remove the directory if it exists
    if CACHE_DIR.exists():
        size = sum(f.stat().st_size for f in CACHE_DIR.rglob("*") if f.is_file())
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        return size

    return 0


def cache_available() -> bool:
    """Return True if the disk cache is operational."""
    return _cache is not None
