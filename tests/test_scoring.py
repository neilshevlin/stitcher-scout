"""Tests for quality and focus scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stitcher.models import RepoInfo
from stitcher.scoring import (
    compute_candidate_rank,
    compute_focus_score,
    compute_repo_quality_score,
    format_quality_signals,
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


# ---------------------------------------------------------------------------
# compute_repo_quality_score
# ---------------------------------------------------------------------------


class TestQualityScore:
    def test_high_quality_repo(self):
        """Many stars, forks, contributors, recent push, CI, license, org-owned, releases."""
        repo = _make_repo(
            stars=5000,
            forks=500,
            contributors_count=50,
            release_count=20,
            has_ci=True,
            has_license=True,
            org_owned=True,
            last_pushed=datetime.now(timezone.utc) - timedelta(days=5),
            created_at=datetime.now(timezone.utc) - timedelta(days=1500),
        )
        score = compute_repo_quality_score(repo)
        assert score > 0.7, f"High-quality repo should score > 0.7, got {score}"

    def test_zero_signal_repo(self):
        """0 stars, 0 forks, 1 contributor, no CI, no license -- minimal signals."""
        repo = _make_repo(
            stars=0,
            forks=0,
            contributors_count=1,
            has_ci=False,
            has_license=False,
            license_name=None,
            org_owned=False,
            release_count=0,
            last_pushed=None,
            created_at=None,
        )
        score = compute_repo_quality_score(repo)
        assert score < 0.3, f"Zero-signal repo should score < 0.3, got {score}"

    def test_archived_repo_includes_zero_active_penalty(self):
        """An archived repo should have the active signal scored as 0.0."""
        repo = _make_repo(archived=True)
        score_archived = compute_repo_quality_score(repo)

        repo_active = _make_repo(archived=False)
        score_active = compute_repo_quality_score(repo_active)

        # The active signal has weight 0.05 and scores 0.0 for archived vs 1.0.
        # So archived should be strictly lower.
        assert score_archived < score_active
        # Verify the gap is roughly 0.05 (the weight of the active signal).
        diff = score_active - score_archived
        assert 0.04 <= diff <= 0.06, f"Active penalty diff should be ~0.05, got {diff}"

    def test_stars_only_mid_range(self):
        """A repo with decent stars but nothing else should land in the middle."""
        repo = _make_repo(
            stars=1000,
            forks=0,
            contributors_count=1,
            has_ci=False,
            has_license=False,
            license_name=None,
            org_owned=False,
            release_count=0,
            last_pushed=None,
            created_at=None,
            archived=False,
        )
        score = compute_repo_quality_score(repo)
        assert 0.15 < score < 0.55, f"Stars-only repo should be mid-range, got {score}"

    def test_score_always_in_unit_range(self):
        repo = _make_repo()
        score = compute_repo_quality_score(repo)
        assert 0.0 <= score <= 1.0

    def test_low_quality_repo(self):
        repo = _make_repo(
            stars=1,
            forks=0,
            contributors_count=1,
            has_ci=False,
            has_license=False,
            org_owned=False,
            release_count=0,
            archived=True,
            last_pushed=datetime.now(timezone.utc) - timedelta(days=1000),
            created_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        score = compute_repo_quality_score(repo)
        assert score < 0.3


# ---------------------------------------------------------------------------
# compute_focus_score
# ---------------------------------------------------------------------------


class TestFocusScore:
    def test_name_matches_search_terms_high_score(self):
        """Repo name contains search terms -- should score 0.8-1.0."""
        repo = _make_repo(full_name="org/midi-parser", description="A MIDI file parser")
        score = compute_focus_score(repo, ["midi", "parser"])
        assert 0.8 <= score <= 1.0, f"Name match should give 0.8-1.0, got {score}"

    def test_name_match_single_term(self):
        """Name matches one term, but match_ratio < 0.5 -- should still be 0.8."""
        repo = _make_repo(
            full_name="org/midi-tools",
            description="Audio utilities",
        )
        score = compute_focus_score(repo, ["midi", "synthesizer", "keyboard"])
        # "midi" is in the name, but only 1/3 terms match => name_match=True, ratio < 0.5 => 0.8
        assert score == 0.8

    def test_description_only_match_moderate_score(self):
        """Only description matches, not repo name -- moderate score."""
        repo = _make_repo(
            full_name="org/cool-project",
            description="MIDI synthesizer library",
        )
        score = compute_focus_score(repo, ["midi", "synthesizer"])
        # Both terms appear in description (match_ratio=1.0) but not in name.
        # name_match=False, match_ratio >= 0.5 => 0.7
        assert score == 0.7

    def test_no_terms_match_low_score(self):
        """No search terms appear anywhere -- should return 0.1."""
        repo = _make_repo(full_name="org/firefox", description="A web browser")
        score = compute_focus_score(repo, ["midi", "synthesizer"])
        assert score == 0.1

    def test_empty_search_terms_neutral(self):
        """Empty search terms list should return neutral 0.5."""
        repo = _make_repo()
        score = compute_focus_score(repo, [])
        assert score == 0.5

    def test_short_terms_filtered_out(self):
        """Terms shorter than 2 characters should be ignored, falling back to 0.5."""
        repo = _make_repo()
        score = compute_focus_score(repo, ["a", "b"])
        assert score == 0.5

    def test_partial_term_match_returns_0_4(self):
        """Some but not half of the terms match -- score is 0.4."""
        repo = _make_repo(
            full_name="org/something",
            description="A library for audio processing",
        )
        # Only "audio" matches (1/3), name doesn't match any.
        score = compute_focus_score(repo, ["audio", "midi", "synthesizer"])
        assert score == 0.4


# ---------------------------------------------------------------------------
# compute_candidate_rank
# ---------------------------------------------------------------------------


class TestCandidateRank:
    def test_focused_small_beats_unfocused_large(self):
        """A focused 200-star library should beat an unfocused 10k-star repo."""
        focused = _make_repo(
            full_name="org/midi-lib",
            description="MIDI library",
            stars=200,
            quality_score=0.4,
        )
        unfocused = _make_repo(
            full_name="org/big-browser",
            description="Web browser",
            stars=10000,
            quality_score=0.9,
        )

        focused_rank = compute_candidate_rank(focused, ["midi"])
        unfocused_rank = compute_candidate_rank(unfocused, ["midi"])
        assert focused_rank > unfocused_rank, (
            f"Focused repo ({focused_rank:.3f}) should outrank "
            f"unfocused repo ({unfocused_rank:.3f})"
        )

    def test_blend_is_40_quality_60_focus(self):
        """The rank should be exactly 0.4 * quality + 0.6 * focus."""
        repo = _make_repo(
            full_name="org/midi-parser",
            description="A MIDI parser",
            quality_score=0.5,
        )
        terms = ["midi", "parser"]
        focus = compute_focus_score(repo, terms)
        expected = 0.5 * 0.4 + focus * 0.6
        actual = compute_candidate_rank(repo, terms)
        assert abs(actual - expected) < 1e-9, (
            f"Expected {expected}, got {actual}"
        )

    def test_zero_quality_still_ranks_by_focus(self):
        """Even with quality_score=0, a focused repo should rank above 0."""
        repo = _make_repo(
            full_name="org/midi-lib",
            description="MIDI library",
            quality_score=0.0,
        )
        rank = compute_candidate_rank(repo, ["midi"])
        assert rank > 0.0


# ---------------------------------------------------------------------------
# format_quality_signals
# ---------------------------------------------------------------------------


class TestFormatQualitySignals:
    def test_contains_all_expected_fields(self):
        repo = _make_repo(
            stars=1234,
            forks=56,
            contributors_count=12,
            has_ci=True,
            has_license=True,
            license_name="MIT",
            org_owned=True,
            release_count=7,
            quality_score=0.85,
            last_pushed=datetime.now(timezone.utc) - timedelta(days=3),
            created_at=datetime.now(timezone.utc) - timedelta(days=1200),
        )
        output = format_quality_signals(repo)

        assert "Stars: 1,234" in output
        assert "Forks: 56" in output
        assert "Contributors: 12" in output
        assert "CI/CD: yes" in output
        assert "License: MIT" in output
        assert "Releases: 7" in output
        assert "Owner type: organization" in output
        assert "Quality score: 0.85/1.00" in output
        assert "3 days ago" in output
        assert "3+ years" in output

    def test_pipe_separated_format(self):
        repo = _make_repo()
        output = format_quality_signals(repo)
        assert " | " in output

    def test_no_license_shows_none(self):
        repo = _make_repo(has_license=False, license_name=None)
        output = format_quality_signals(repo)
        assert "License: none" in output

    def test_personal_owner_type(self):
        repo = _make_repo(org_owned=False)
        output = format_quality_signals(repo)
        assert "Owner type: personal" in output

    def test_no_ci(self):
        repo = _make_repo(has_ci=False)
        output = format_quality_signals(repo)
        assert "CI/CD: no" in output

    def test_last_push_today(self):
        repo = _make_repo(last_pushed=datetime.now(timezone.utc))
        output = format_quality_signals(repo)
        assert "Last push: today" in output

    def test_last_push_yesterday(self):
        repo = _make_repo(last_pushed=datetime.now(timezone.utc) - timedelta(days=1))
        output = format_quality_signals(repo)
        assert "Last push: yesterday" in output

    def test_young_repo_shows_months(self):
        repo = _make_repo(created_at=datetime.now(timezone.utc) - timedelta(days=150))
        output = format_quality_signals(repo)
        assert "months" in output
