"""Author a songs-workspace marker — the *write* side of the project-root contract.

The *reader* (`hallucinote.workspace`) discovers a ``hallucinote.toml`` marker and
resolves ``slug → song dir → DB``. Until now nothing *created* that marker: the
README told users to hand-author it, and a missing marker degraded **silently** to
``./songs/<slug>`` relative to cwd (``workspace.py`` precedence step 4) — so a new
user's first ``/song-new`` could scatter a song into whatever directory Claude
happened to launch from, untracked and unmarked.

This module is the author side: a tested, atomic marker write plus a ``--check``
dry-run the onboarding skills use to detect "you're not in a workspace yet" before
they scaffold. See ``.prawduct/artifacts/project-root-contract.md``.

CLI::

    hallucinote init-workspace [DIR] [--layout monorepo|song] [--songs-root songs]
        [--slug SLUG] [--no-git] [--force] [--check]

Default layout is ``monorepo`` — the only build-proven layout (the spike + the
integration tests exercise monorepo-with-one-song; flat ``song`` mislocates its DB
because ``build.py`` hardcodes its root — see the contract's "Still deferred").
Flat ``song`` is accepted with ``--slug`` but warns it is experimental.

Prints a JSON result on stdout (like the other tool CLIs); exit 0 on success,
non-zero on refusal.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from hallucinote.tools.scaffold_song import validate_slug
from hallucinote.workspace import (
    LAYOUT_MONOREPO,
    LAYOUT_SONG,
    MARKER_FILENAME,
    Workspace,
    find_workspace,
)

DEFAULT_SONGS_ROOT = "songs"

# A managed .gitignore block covering everything the toolchain *regenerates* — so a
# freshly-bootstrapped workspace doesn't tempt the user to commit a 30-table SQLite
# DB, capture WAVs, or MixReport JSON. Closes the fresh-workspace half of the filed
# "song-workspace gitignore misses tool-generated artifacts" bug (suggested fix #1).
# Layout-agnostic (`**/`) so it covers monorepo and flat `song` layouts alike.
_GITIGNORE_BEGIN = "# --- Hallucinote: regenerable tool artifacts (managed block) ---"
_GITIGNORE_END = "# --- end Hallucinote managed block ---"
# The workspace-ROOT block. Its per-song-dir counterpart is
# `hallucinote.paths.SONG_DIR_IGNORED_FILES`, which tools write into the song
# dir they generate into (WSP-3R7K) so the ignore reaches workspaces created
# before this block existed. The two overlap deliberately — this one covers a
# freshly-bootstrapped workspace wholesale, that one travels with the artifact
# — but they are separate lists: keep the song-dir names in sync when either
# grows, or a pre-bootstrap workspace stops ignoring something this one does.
GITIGNORE_BLOCK = "\n".join(
    [
        _GITIGNORE_BEGIN,
        "*.db",
        "*.db-wal",
        "*.db-shm",
        "**/captures/",
        "**/analysis/",
        "**/captured_session.json.bak",
        "**/.last-notes-push.json",
        "**/.last-push-state.json",
        "**/.last-push-errors.json",
        "*.als",
        "*.als.bak",
        "__pycache__/",
        "*.pyc",
        _GITIGNORE_END,
        "",
    ]
)


@dataclass(frozen=True)
class InitResult:
    """What ``init_workspace`` did (or, in ``--check`` mode, would do)."""

    directory: str
    marker_path: str
    layout: str
    songs_root: str
    slug: str | None
    written: bool
    already_workspace: bool
    existing_marker: str | None
    git_initialized: bool
    already_git: bool
    gitignore_written: bool
    gitignore_updated: bool


def render_marker(layout: str, songs_root: str, slug: str | None) -> str:
    """Render the ``hallucinote.toml`` body for the chosen layout."""
    head = (
        "# hallucinote.toml — songs-workspace marker.\n"
        "# Marks the root of a Hallucinote songs workspace (discovered like .git).\n"
        "# See docs/quickstart.md and .prawduct/artifacts/project-root-contract.md.\n"
        "[workspace]\n"
    )
    if layout == LAYOUT_SONG:
        return head + f'layout = "{LAYOUT_SONG}"\nslug   = "{slug}"\n'
    return head + (
        f'# "monorepo": many songs under songs_root/<slug>/\n'
        f'layout     = "{LAYOUT_MONOREPO}"\n'
        f'songs_root = "{songs_root}"\n'
    )


def _is_git_repo(directory: Path) -> bool:
    """True if ``directory`` is at or inside a git working tree.

    Walks up for a ``.git`` entry (a dir for a normal repo, a file for a worktree
    / submodule). Avoids a subprocess so ``--check`` and the no-git path stay
    dependency-free and hermetic in tests.
    """
    for d in (directory, *directory.parents):
        if (d / ".git").exists():
            return True
    return False


def _write_gitignore(directory: Path) -> tuple[bool, bool]:
    """Ensure ``directory/.gitignore`` carries the Hallucinote managed block.

    Returns ``(written_new, appended)``: ``written_new`` if no ``.gitignore``
    existed and one was created; ``appended`` if an existing ``.gitignore`` gained
    the block. Idempotent — re-running when the block is already present is a no-op
    (returns ``(False, False)``) and never duplicates or clobbers user content.
    """
    gi = directory / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE_BLOCK, encoding="utf-8")
        return True, False
    existing = gi.read_text(encoding="utf-8")
    if _GITIGNORE_BEGIN in existing:
        return False, False  # already managed — leave it alone
    sep = "" if existing.endswith("\n") else "\n"
    gi.write_text(existing + sep + "\n" + GITIGNORE_BLOCK, encoding="utf-8")
    return False, True


def init_workspace(
    directory: Path,
    *,
    layout: str = LAYOUT_MONOREPO,
    songs_root: str = DEFAULT_SONGS_ROOT,
    slug: str | None = None,
    git: bool = True,
    gitignore: bool = True,
    force: bool = False,
    check: bool = False,
) -> InitResult:
    """Write a ``hallucinote.toml`` marker into ``directory`` (atomically).

    Refuses (raises ``FileExistsError``) when ``directory`` is at or inside an
    existing workspace, unless ``force`` is set — an accidental nested workspace
    would shadow song resolution. With ``check=True`` nothing is written and no
    ``git init`` runs; the result reports what *would* happen.

    Raises ``ValueError`` on an invalid layout, or a ``song`` layout missing a
    (valid) ``slug``.
    """
    directory = directory.resolve()
    if layout not in (LAYOUT_MONOREPO, LAYOUT_SONG):
        raise ValueError(
            f"invalid layout {layout!r}: expected {LAYOUT_MONOREPO!r} or {LAYOUT_SONG!r}"
        )
    if layout == LAYOUT_SONG:
        if not slug:
            raise ValueError(
                'layout "song" requires --slug (the single song this repo holds)'
            )
        validate_slug(slug)
    else:
        slug = None  # slug is meaningless for a monorepo marker

    existing: Workspace | None = find_workspace(start=directory)
    already_workspace = existing is not None
    existing_marker = (
        str(existing.root / MARKER_FILENAME) if existing is not None else None
    )

    marker_path = directory / MARKER_FILENAME
    already_git = _is_git_repo(directory)

    if check:
        return InitResult(
            directory=str(directory),
            marker_path=str(marker_path),
            layout=layout,
            songs_root=songs_root if layout == LAYOUT_MONOREPO else ".",
            slug=slug,
            written=False,
            already_workspace=already_workspace,
            existing_marker=existing_marker,
            git_initialized=False,
            already_git=already_git,
            gitignore_written=False,
            gitignore_updated=False,
        )

    if already_workspace and not force:
        raise FileExistsError(
            f"already inside a workspace (marker at {existing_marker}). "
            "Use --force to create a nested marker here anyway (this shadows the "
            "outer workspace for songs at or below this directory)."
        )

    directory.mkdir(parents=True, exist_ok=True)
    body = render_marker(layout, songs_root, slug)
    # Atomic write: temp file in the same dir, then os.replace (single rename).
    tmp = marker_path.with_suffix(".toml.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, marker_path)

    gitignore_written = gitignore_updated = False
    if gitignore:
        gitignore_written, gitignore_updated = _write_gitignore(directory)

    git_initialized = False
    if git and not already_git:
        try:
            subprocess.run(
                ["git", "init"],
                cwd=str(directory),
                check=True,
                capture_output=True,
            )
            git_initialized = True
        except (OSError, subprocess.CalledProcessError):
            # The marker is the essential artifact; a failed/absent git is a
            # convenience miss, not a reason to fail the whole init. Reported via
            # git_initialized=False so the caller can mention it.
            git_initialized = False

    return InitResult(
        directory=str(directory),
        marker_path=str(marker_path),
        layout=layout,
        songs_root=songs_root if layout == LAYOUT_MONOREPO else ".",
        slug=slug,
        written=True,
        already_workspace=already_workspace,
        existing_marker=existing_marker,
        git_initialized=git_initialized,
        already_git=already_git,
        gitignore_written=gitignore_written,
        gitignore_updated=gitignore_updated,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hallucinote init-workspace",
        description="Create a hallucinote.toml songs-workspace marker.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="workspace root to mark (default: current directory)",
    )
    parser.add_argument(
        "--layout",
        choices=[LAYOUT_MONOREPO, LAYOUT_SONG],
        default=LAYOUT_MONOREPO,
        help=f"workspace layout (default: {LAYOUT_MONOREPO})",
    )
    parser.add_argument(
        "--songs-root",
        default=DEFAULT_SONGS_ROOT,
        help=f"songs subdir for monorepo layout (default: {DEFAULT_SONGS_ROOT})",
    )
    parser.add_argument(
        "--slug", default=None, help='song slug (required for --layout song)'
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="do not run `git init` (default: init if not already a repo)",
    )
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="do not write/append the regenerable-artifacts .gitignore block",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="create a marker even inside an existing workspace",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report workspace status without writing anything (dry run)",
    )
    args = parser.parse_args(argv)

    try:
        result = init_workspace(
            Path(args.directory),
            layout=args.layout,
            songs_root=args.songs_root,
            slug=args.slug,
            git=not args.no_git,
            gitignore=not args.no_gitignore,
            force=args.force,
            check=args.check,
        )
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    except FileExistsError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    if result.layout == LAYOUT_SONG:
        # The reader supports flat `song` layout, but build.py still hardcodes
        # root=parent.parent (project-root-contract "Still deferred"), so a flat
        # repo's build mislocates its DB. Warn rather than hand over a silent
        # footgun; monorepo is the build-proven default.
        print(
            'warning: layout "song" (flat repo) is experimental — build.py does not '
            "yet resolve its DB for this layout; prefer the default monorepo layout.",
            file=sys.stderr,
        )

    print(json.dumps({"ok": True, **asdict(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
