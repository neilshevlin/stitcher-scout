"""Tests for quality and focus scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stitcher.models import RepoInfo
from stitcher.scoring import (
    compute_candidate_rank,
    compute_focus_score,
    compute_repo_quality_score,
)


def _make_repo(**kwargs) -> RepoInfo:
    defaults = {
        "full_name": "org/test-repo",
        "url": "https://github.com/org/test-repo",
        "description": "A test repository",
        "stars": 100,
        "forks": 20,
        "contributors_count": 5,
        "has_ci": True,
        "has_license": True,
        "license_name": "MIT",
        "org_owned": True,
        "release_count": 3,
        "last_pushed": datetime.now(timezone.utc) - timedelta(days=10),
        "created_at": datetime.now(timezone.utc) - timedelta(days=800),
    }
    defaults.update(kwargs)
    return RepoInfo(**defaults)


class TestQualityScore:
    def test_high_quality_repo(self):
        repo = _make_repo(stars=5000, forks=500, contributors_count=50, release_count=20)
        score = compute_repo_quality_score(repo)
        assert score > 0.7

    def test_low_quality_repo(self):
        repo = _make_repo(
            stars=1, forks=0, contributors_count=1,
            has_ci=False, has_license=False, org_owned=False,
            release_count=0, archived=True,
            last_pushed=datetime.now(timezone.utc) - timedelta(days=1000),
            created_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        score = compute_repo_quality_score(repo)
        assert score < 0.3

    def test_score_in_range(self):
        repo = _make_repo()
        score = compute_repo_quality_score(repo)
        assert 0.0 <= score <= 1.0

    def test_archived_penalized(self):
        active = _make_repo(archived=False)
        archived = _make_repo(archived=True)
        assert compute_repo_quality_score(active) > compute_repo_quality_score(archived)


class TestFocusScore:
    def test_name_match_high_score(self):
        repo = _make_repo(full_name="org/midi-parser", description="A MIDI file parser")
        score = compute_focus_score(repo, ["midi", "parser"])
        assert score == 1.0

    def test_no_match_low_score(self):
        repo = _make_repo(full_name="org/firefox", description="A web browser")
        score = compute_focus_score(repo, ["midi", "synthesizer"])
        assert score <= 0.2

    def test_description_only_match(self):
        repo = _make_repo(full_name="org/cool-project", description="MIDI synthesizer library")
        score = compute_focus_score(repo, ["midi", "synthesizer"])
        assert 0.5 < score < 1.0

    def test_empty_terms_neutral(self):
        repo = _make_repo()
        score = compute_focus_score(repo, [])
        assert score == 0.5


class TestCandidateRank:
    def test_focused_small_beats_unfocused_large(self):
        focused = _make_repo(full_name="org/midi-lib", description="MIDI library", stars=200, quality_score=0.4)
        unfocused = _make_repo(full_name="org/big-browser", description="Web browser", stars=10000, quality_score=0.9)

        focused_rank = compute_candidate_rank(focused, ["midi"])
        unfocused_rank = compute_candidate_rank(unfocused, ["midi"])
        assert focused_rank > unfocused_rank
