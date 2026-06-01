"""W12-A — per-branch DB filename resolution.

`resolve_db_path` returns `songs/<slug>/<slug>-<branch>.db` inside a repo
and `songs/<slug>/<slug>.db` outside one (or on detached HEAD). The branch
parameter is an escape hatch so these tests don't depend on the actual
git state of the working tree.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from hallucinote.db.connection import _git_current_branch, resolve_db_path


# ---------------------------------------------------------------------------
# resolve_db_path — explicit branch (escape hatch)
# ---------------------------------------------------------------------------


def test_explicit_branch_main():
    path = resolve_db_path("falling-walking", branch="main")
    assert path == Path("songs") / "falling-walking" / "falling-walking-main.db"


def test_explicit_branch_with_slash_sanitized():
    """feat/wave-12 -> feat--wave-12. Mirrors .prawduct/.pr-reviews/ naming."""
    path = resolve_db_path("falling-walking", branch="feat/wave-12")
    assert path == Path("songs") / "falling-walking" / "falling-walking-feat--wave-12.db"


def test_explicit_branch_none_falls_back_to_legacy_name():
    """Detached HEAD / outside-repo case: drop the branch suffix entirely."""
    path = resolve_db_path("falling-walking", branch=None)
    assert path == Path("songs") / "falling-walking" / "falling-walking.db"


def test_explicit_branch_with_nested_slashes():
    """feature/foo/bar -> feature--foo--bar."""
    path = resolve_db_path("solo-piano-ambient", branch="feature/foo/bar")
    assert path.name == "solo-piano-ambient-feature--foo--bar.db"


def test_custom_root():
    """Tests + tools use this with a tmp root."""
    path = resolve_db_path(
        "falling-walking", root=Path("/tmp/test-songs"), branch="main"
    )
    assert path == Path("/tmp/test-songs/falling-walking/falling-walking-main.db")


def test_root_as_string():
    """Path-or-str is accepted for ergonomics."""
    path = resolve_db_path("solo-piano-ambient", root="my-songs", branch="dev")
    assert path == Path("my-songs/solo-piano-ambient/solo-piano-ambient-dev.db")


# ---------------------------------------------------------------------------
# resolve_db_path — git probe path
# ---------------------------------------------------------------------------


def test_git_probe_used_when_no_branch_arg():
    """No branch arg -> probes git via _git_current_branch."""
    with patch("hallucinote.db.connection._git_current_branch", return_value="my-branch"):
        path = resolve_db_path("falling-walking")
    assert path.name == "falling-walking-my-branch.db"


def test_git_probe_returns_none_uses_legacy_name():
    """Outside a repo / detached HEAD -> legacy filename."""
    with patch("hallucinote.db.connection._git_current_branch", return_value=None):
        path = resolve_db_path("falling-walking")
    assert path.name == "falling-walking.db"


# ---------------------------------------------------------------------------
# _git_current_branch — direct probe
# ---------------------------------------------------------------------------


def test_git_probe_returns_string_on_real_repo():
    """When called inside this repo (or any repo), returns the branch name."""
    branch = _git_current_branch()
    # Either inside a repo (returns non-empty str) or outside (None) — both
    # valid. The contract: never returns empty string.
    assert branch is None or (isinstance(branch, str) and len(branch) > 0)


def test_git_probe_returns_none_outside_repo(tmp_path):
    """When cwd isn't a git repo, returns None."""
    branch = _git_current_branch(cwd=tmp_path)
    assert branch is None


def test_git_probe_returns_none_when_git_missing():
    """If `git` isn't on PATH, return None instead of raising."""
    with patch("hallucinote.db.connection.shutil.which", return_value=None):
        branch = _git_current_branch()
    assert branch is None


def test_git_probe_returns_none_on_detached_head(tmp_path):
    """Detached HEAD: `git symbolic-ref --short HEAD` exits non-zero -> None."""
    # Set up a real git repo with a detached HEAD
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        # `-c commit.gpgsign=false` keeps the throwaway commit hermetic: without
        # it the temp repo inherits any ambient commit-signing config (e.g. a
        # signing-server hook), which is irrelevant to detached-HEAD probing.
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "commit",
         "--allow-empty", "-q", "-m", "initial"],
        cwd=repo, check=True,
    )
    # Get the commit sha and check it out (detaches HEAD)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "checkout", "-q", "--detach", sha], cwd=repo, check=True,
    )
    branch = _git_current_branch(cwd=repo)
    assert branch is None
