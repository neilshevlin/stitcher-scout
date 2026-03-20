"""Weighted quality scoring for repositories based on signals."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .models import RepoInfo


def compute_repo_quality_score(repo: RepoInfo) -> float:
    """Compute a 0.0-1.0 quality score from repository signals.

    Weights reflect how strongly each signal indicates a trustworthy,
    production-quality codebase.
    """
    scores: dict[str, tuple[float, float]] = {}  # signal -> (score, weight)

    # --- Stars (log scale, diminishing returns) ---
    # 0 stars = 0.0, 10 = 0.3, 100 = 0.6, 1000 = 0.8, 10000 = 1.0
    if repo.stars > 0:
        star_score = min(1.0, math.log10(repo.stars) / 4.0)
    else:
        star_score = 0.0
    scores["stars"] = (star_score, 0.20)

    # --- Forks (log scale, indicates real usage) ---
    if repo.forks > 0:
        fork_score = min(1.0, math.log10(repo.forks) / 3.0)
    else:
        fork_score = 0.0
    scores["forks"] = (fork_score, 0.10)

    # --- Contributors (more = better, diminishing returns) ---
    if repo.contributors_count >= 10:
        contrib_score = 1.0
    elif repo.contributors_count >= 5:
        contrib_score = 0.8
    elif repo.contributors_count >= 3:
        contrib_score = 0.6
    elif repo.contributors_count >= 2:
        contrib_score = 0.4
    else:
        contrib_score = 0.1
    scores["contributors"] = (contrib_score, 0.15)

    # --- Recency (last push within 6 months = good) ---
    if repo.last_pushed:
        days_since_push = (datetime.now(timezone.utc) - repo.last_pushed).days
        if days_since_push <= 30:
            recency_score = 1.0
        elif days_since_push <= 90:
            recency_score = 0.8
        elif days_since_push <= 180:
            recency_score = 0.6
        elif days_since_push <= 365:
            recency_score = 0.3
        else:
            recency_score = 0.1
    else:
        recency_score = 0.0
    scores["recency"] = (recency_score, 0.10)

    # --- Repo age (older + still active = mature) ---
    if repo.created_at:
        age_days = (datetime.now(timezone.utc) - repo.created_at).days
        if age_days >= 1095:  # 3+ years
            age_score = 1.0
        elif age_days >= 730:  # 2+ years
            age_score = 0.8
        elif age_days >= 365:  # 1+ year
            age_score = 0.6
        elif age_days >= 90:   # 3+ months
            age_score = 0.3
        else:
            age_score = 0.1
    else:
        age_score = 0.0
    scores["age"] = (age_score, 0.05)

    # --- CI/CD presence ---
    scores["ci"] = (1.0 if repo.has_ci else 0.0, 0.10)

    # --- License presence ---
    scores["license"] = (1.0 if repo.has_license else 0.0, 0.05)

    # --- Org-owned ---
    scores["org"] = (1.0 if repo.org_owned else 0.3, 0.10)

    # --- Releases (proper versioning) ---
    if repo.release_count >= 5:
        release_score = 1.0
    elif repo.release_count >= 2:
        release_score = 0.7
    elif repo.release_count >= 1:
        release_score = 0.4
    else:
        release_score = 0.0
    scores["releases"] = (release_score, 0.10)

    # --- Not archived (hard filter, but contribute to score too) ---
    scores["active"] = (0.0 if repo.archived else 1.0, 0.05)

    # Weighted sum
    total = sum(score * weight for score, weight in scores.values())
    total_weight = sum(weight for _, weight in scores.values())

    return round(total / total_weight, 3) if total_weight > 0 else 0.0


def compute_focus_score(repo: RepoInfo, search_terms: list[str]) -> float:
    """Score how focused a repo is on the search topic (0.0-1.0).

    A 200-star MIDI library should rank above a 10,000-star web browser
    that happens to have a MIDI module. This function measures whether
    the repo is *primarily about* the topic.
    """
    if not search_terms:
        return 0.5  # No terms to match, neutral

    # Normalize search terms
    terms = [t.lower().strip() for t in search_terms if len(t.strip()) >= 2]
    if not terms:
        return 0.5

    # Build a bag of words from repo name, description, and topics
    text_parts = [repo.full_name.replace("/", " ").replace("-", " ").replace("_", " ")]
    if repo.description:
        text_parts.append(repo.description)
    if repo.topics:
        text_parts.extend(repo.topics)
    bag = " ".join(text_parts).lower()

    # Count how many search terms appear in the repo's identity
    matches = sum(1 for term in terms if term in bag)
    match_ratio = matches / len(terms)

    # Check if the repo NAME (not just description) contains a key term
    # This is a strong signal that the repo is focused on the topic
    repo_name = repo.full_name.split("/")[-1].lower().replace("-", " ").replace("_", " ")
    name_match = any(term in repo_name for term in terms)

    if name_match and match_ratio >= 0.5:
        return 1.0
    elif name_match:
        return 0.8
    elif match_ratio >= 0.5:
        return 0.7
    elif match_ratio > 0:
        return 0.4
    else:
        return 0.1  # No term appears anywhere — likely an incidental match


def compute_candidate_rank(repo: RepoInfo, search_terms: list[str]) -> float:
    """Compute a ranking score that blends repo quality with topic focus.

    Used to decide which candidates to send to the (expensive) LLM evaluator.
    Focused repos get a boost; large unfocused repos get penalized.
    """
    quality = repo.quality_score
    focus = compute_focus_score(repo, search_terms)

    # Blend: 40% quality, 60% focus
    # This ensures a focused 200-star library beats an unfocused 10k-star browser
    return quality * 0.4 + focus * 0.6


def format_quality_signals(repo: RepoInfo) -> str:
    """Format quality signals as a human-readable string for the LLM evaluation prompt."""
    parts = []
    parts.append(f"Stars: {repo.stars:,}")
    parts.append(f"Forks: {repo.forks:,}")
    parts.append(f"Contributors: {repo.contributors_count}")

    if repo.last_pushed:
        days = (datetime.now(timezone.utc) - repo.last_pushed).days
        if days == 0:
            parts.append("Last push: today")
        elif days == 1:
            parts.append("Last push: yesterday")
        else:
            parts.append(f"Last push: {days} days ago")

    if repo.created_at:
        age_days = (datetime.now(timezone.utc) - repo.created_at).days
        years = age_days // 365
        if years >= 1:
            parts.append(f"Repo age: {years}+ years")
        else:
            months = age_days // 30
            parts.append(f"Repo age: {months} months")

    parts.append(f"CI/CD: {'yes' if repo.has_ci else 'no'}")
    parts.append(f"License: {repo.license_name or 'none'}")
    parts.append(f"Releases: {repo.release_count}")
    parts.append(f"Owner type: {'organization' if repo.org_owned else 'personal'}")
    parts.append(f"Quality score: {repo.quality_score:.2f}/1.00")

    return " | ".join(parts)
