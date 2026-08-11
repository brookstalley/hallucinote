"""WSP-3R7K — tool-written artifacts ignore themselves where they are written.

`hallucinote init-workspace` writes a managed root `.gitignore`, but only for
workspaces bootstrapped THROUGH it. A workspace created before that shipped, or
by a bare `git init`, never gets the block — so every render and every push kept
surfacing MixReports, push-state caches and snapshot backups as committable.

The durable fix is per-tool: ignore the output at the moment it is created, so
the ignore travels with the artifact regardless of how the workspace was made.
"""
from __future__ import annotations

from pathlib import Path

from hallucinote.paths import (
    SONG_DIR_IGNORED_FILES,
    self_ignore_dir,
    self_ignore_files,
)


# --- self_ignore_dir: whole-directory output (analysis/, captures/) ----------


def test_self_ignore_dir_ignores_everything_including_itself(tmp_path: Path):
    """`*` covers the .gitignore too, so the marker itself is never committable
    and never shows up in `git status`."""
    d = tmp_path / "analysis"
    d.mkdir()
    self_ignore_dir(d)

    body = (d / ".gitignore").read_text()
    assert body.splitlines()[-1] == "*"
    assert "Managed by Hallucinote" in body


def test_self_ignore_dir_creates_a_missing_directory(tmp_path: Path):
    d = tmp_path / "captures"
    self_ignore_dir(d)
    assert (d / ".gitignore").exists()


def test_self_ignore_dir_is_idempotent_and_does_not_rewrite(tmp_path: Path):
    """Called on every analysis run, so it must not churn the file's mtime."""
    d = tmp_path / "analysis"
    self_ignore_dir(d)
    target = d / ".gitignore"
    before = target.stat().st_mtime_ns

    self_ignore_dir(d)

    assert target.stat().st_mtime_ns == before
    assert target.read_text().count("*") == 1


def test_self_ignore_dir_never_raises_on_an_unwritable_target(tmp_path: Path):
    """Disk hygiene must never take down the render it was tidying after."""
    d = tmp_path / "analysis"
    d.mkdir()
    (d / ".gitignore").mkdir()  # a directory where the file should go -> OSError

    self_ignore_dir(d)  # must not raise


# --- self_ignore_files: the song dir, which also holds authored work ---------


def test_self_ignore_files_lists_names_and_never_blankets_the_song_dir(tmp_path):
    """A `*` here would ignore build.py and captured_session.json — the song
    itself. Only the generated names may appear."""
    song = tmp_path / "the-argument"
    song.mkdir()
    self_ignore_files(song, SONG_DIR_IGNORED_FILES)

    lines = [
        ln for ln in (song / ".gitignore").read_text().splitlines()
        if ln and not ln.startswith("#")
    ]
    assert "*" not in lines
    assert set(lines) == set(SONG_DIR_IGNORED_FILES)


def test_self_ignore_files_merges_with_existing_entries(tmp_path: Path):
    """A song dir has several writers, and the user may have their own entries;
    neither may be clobbered."""
    song = tmp_path / "the-argument"
    song.mkdir()
    (song / ".gitignore").write_text("scratch/\n*.wav\n")

    self_ignore_files(song, [".last-push-state.json"])

    lines = (song / ".gitignore").read_text().splitlines()
    assert "scratch/" in lines
    assert "*.wav" in lines
    assert ".last-push-state.json" in lines


def test_self_ignore_files_does_not_duplicate_on_repeat_calls(tmp_path: Path):
    song = tmp_path / "the-argument"
    song.mkdir()
    for _ in range(3):
        self_ignore_files(song, SONG_DIR_IGNORED_FILES)

    lines = (song / ".gitignore").read_text().splitlines()
    for name in SONG_DIR_IGNORED_FILES:
        assert lines.count(name) == 1


def test_self_ignore_files_is_a_no_op_for_an_empty_list(tmp_path: Path):
    song = tmp_path / "the-argument"
    song.mkdir()
    self_ignore_files(song, [])
    assert not (song / ".gitignore").exists()


def test_the_song_dir_names_are_a_subset_of_the_workspace_root_block(tmp_path):
    """WSP-3R7K parity lock. `paths.SONG_DIR_IGNORED_FILES` (travels with the
    artifact, for workspaces that predate the bootstrap) and
    `init_workspace.GITIGNORE_BLOCK` (covers a fresh workspace wholesale) are a
    mirrored contract kept in step only by a comment.

    Add a name to one and not the other, and a pre-bootstrap workspace silently
    stops ignoring it — #303's exact symptom back, with nothing red. Pin it.
    """
    from hallucinote.tools.init_workspace import GITIGNORE_BLOCK

    root_entries = {
        line.strip().lstrip("*/") for line in GITIGNORE_BLOCK.splitlines()
    }
    missing = [
        name for name in SONG_DIR_IGNORED_FILES
        if name not in root_entries
    ]
    assert not missing, (
        f"{missing} self-ignore in the song dir but are absent from the "
        "workspace-root block — a freshly-bootstrapped workspace would stop "
        "ignoring them. Add them to init_workspace.GITIGNORE_BLOCK too."
    )
