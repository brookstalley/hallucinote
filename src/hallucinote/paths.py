"""Path references in persisted artifacts (CLP-AUD1, AUD-PORTPATH).

Two directions of the same rule: **a path that gets written down is
written down portably.** ``clips.audio_file`` stores the reference
exactly as authored — a song-relative POSIX path (canonically under
``assets/``, where AUD-9R3V's recorded takes will also land) or an
absolute path — and :func:`resolve_audio_path` is the single
resolution point (the push planners and analysis ingest resolve through
it), so the DB never stores a resolved path and the private songs repo
stays portable across machines and collaborators.

:func:`portable_path` / :func:`resolve_portable_path` are the write /
read halves of that same contract for **artifacts we check in** — the
MixReport JSONs under ``songs/<slug>/analysis/`` (git-tracked by
policy, see ``.gitignore``). A machine-absolute path in one of those
commits the author's home directory into the repo, defeats diffing
across machines, and is exactly what ``tools/tour_transcript.py``
refuses to publish.

Lives at the package top level rather than under ``hallucinote.audio``
because that package eagerly imports the numpy-bound analysis stack at
``__init__`` time; path resolution must stay importable from
stdlib-only contexts (the MCP server is stdlib-only at startup and the
sync layer carries no heavy deps).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def resolve_audio_path(song_dir: str | Path, ref: str) -> Path:
    """Resolve a ``clips.audio_file`` reference against a song directory.

    Relative refs are POSIX-separated by contract and resolve under
    ``song_dir`` — the directory containing the song's ``build.py``;
    the helper takes it as an explicit argument so the policy stays
    caller-owned. Absolute refs pass through unchanged (stored
    as-given; the push-time existence check lives in the clips phase).
    """
    posix_ref = PurePosixPath(ref)
    if posix_ref.is_absolute() or Path(ref).is_absolute():
        return Path(ref)
    return Path(song_dir).joinpath(*posix_ref.parts)


def portable_path(path: str | Path, *, base: str | Path | None) -> str:
    """Render ``path`` for PERSISTENCE in a checked-in artifact.

    Three forms, in order of preference:

    1. **``base``-relative POSIX** (``captures/20260807T161909Z``) when
       ``path`` lives under ``base``. This is the form we want: it is
       the same song-relative convention ``clips.audio_file`` uses, it
       diffs identically on every machine, and the consumer resolves it
       with :func:`resolve_portable_path` against the same anchor.
    2. **``~``-collapsed** (``~/source/other/captures/x``) when ``path``
       is outside ``base`` but under the current user's home. Nothing
       anchors it song-relatively, but the account name — the thing that
       actually leaks — is gone, and the path stays locatable for the
       user who wrote it.
    3. **Absolute POSIX**, unchanged, for anything else (``/Volumes/…``,
       a CI temp dir). Such a path names no account, so there is nothing
       to redact; rewriting it would only lose information.

    ``base`` is the anchor the *writer* chooses, and it must be the one
    the reader can rediscover from the artifact itself — for analyzer
    output that is the song directory (the analysis dir's parent). Pass
    ``None`` when no anchor is available; the ``~``/absolute fallbacks
    still apply, so the account name never survives either way.

    Path comparison is textual first and filesystem-normalized second: a
    caller may hand a resolved path (``Path.resolve()`` follows
    ``/tmp`` → ``/private/tmp`` on macOS) alongside an unresolved base,
    and a purely textual containment check would silently miss the
    relation and fall through to form 2.
    """
    p = Path(path)
    if base is not None:
        rel = _relative_or_none(p, Path(base))
        if rel is not None:
            return rel
    home = Path.home()
    rel_home = _relative_or_none(p, home)
    if rel_home is not None:
        return "~" if rel_home == "." else f"~/{rel_home}"
    return p.as_posix()


def resolve_portable_path(base: str | Path, ref: str) -> Path:
    """Resolve a :func:`portable_path` reference back to a real path.

    The read-side tolerance for all three written forms — and for the
    machine-absolute paths older artifacts carry, which are simply
    form 3 and pass through unchanged. ``base`` is the anchor the writer
    used (for a MixReport: the song directory, i.e. the parent of the
    directory the report was read from).

    Home expansion goes through ``Path.home()`` rather than
    ``Path.expanduser()`` so the two halves share ONE definition of home:
    ``expanduser`` keys on the ``HOME`` environment variable, which can
    disagree with what :func:`portable_path` collapsed against. Only the
    ``~``/``~/…`` form this module emits is expanded; a ``~user/…`` ref
    (never written here) is treated as an ordinary relative reference.
    """
    if ref == "~":
        return Path.home()
    if ref.startswith("~/"):
        return Path.home().joinpath(*PurePosixPath(ref[2:]).parts)
    return resolve_audio_path(base, ref)


def portable_text(text: str) -> str:
    """Collapse this machine's home directory wherever it appears in FREE TEXT.

    The blunt companion to :func:`portable_path`, for the prose we persist —
    a teaching error message quoted into a checked-in ``status.json``. A
    structured field knows what it holds and gets the full three-form
    treatment; a message does not, so this rewrites exactly one thing: the
    literal local home prefix, the only part that carries an account name.
    It deliberately does NOT hunt for path shapes in arbitrary text — that is
    the transcript renderer's job (``tools/tour_transcript.py``), which fails
    closed because it publishes; this one only has to stop us committing our
    own home directory.

    A degenerate home (empty, or ``/``) is left alone rather than rewritten
    into nonsense.
    """
    home = str(Path.home())
    if home in ("", "/"):
        return text
    return text.replace(home, "~")


def _relative_or_none(path: Path, base: Path) -> str | None:
    """``path`` relative to ``base`` as a POSIX string, or None if outside.

    Tries the paths as given, then again with both filesystem-normalized
    (``resolve()`` is non-strict, so a not-yet-created dir is fine) —
    see :func:`portable_path`'s note on ``/tmp`` vs ``/private/tmp``.
    """
    for candidate, anchor in ((path, base), (path.resolve(), base.resolve())):
        try:
            return candidate.relative_to(anchor).as_posix()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Self-ignoring tool output (WSP-3R7K)
# ---------------------------------------------------------------------------
#
# `hallucinote init-workspace` writes a managed root `.gitignore` covering
# regenerable tool output — but only for workspaces bootstrapped THROUGH it.
# A workspace created before that shipped, or by a bare `git init`, never gets
# the block, so every render and every push keeps surfacing MixReports, push
# state caches and snapshot backups as committable noise.
#
# The durable fix is for each generating tool to ignore its own output at the
# moment it creates it: the ignore then travels WITH the artifact regardless of
# when or how the workspace was made, and a fresh clone needs no root-file edit.

# The regenerable files tools write INTO the song directory, which also holds
# authored work (build.py, captured_session.json, decisions/). Listed by name so
# the ignore covers exactly these — a blanket `*` here would swallow the song.
# Any tool that writes one of them ignores the whole family, so whichever runs
# first covers the rest. Overlaps `init_workspace.GITIGNORE_BLOCK`, the
# workspace-ROOT list, on purpose: that one covers a freshly-bootstrapped
# workspace wholesale, this one travels with the artifact into workspaces that
# predate it. Keep the song-dir names in sync when either grows.
SONG_DIR_IGNORED_FILES = (
    ".last-notes-push.json",
    ".last-push-state.json",
    ".last-push-errors.json",
    "captured_session.json.bak",
)

_MANAGED_HEADER = (
    "# Managed by Hallucinote — regenerable tool output, safe to delete.\n"
    "# Rewritten if removed; edit the workspace root .gitignore instead.\n"
)


def self_ignore_dir(directory: Path) -> None:
    """Mark a whole directory of regenerable output as ignored.

    Writes ``<directory>/.gitignore`` containing ``*`` — which ignores the
    ``.gitignore`` itself too, so nothing here is ever committable and the file
    is invisible in `git status`.

    For directories whose ENTIRE contents are regenerable — ``captures/`` is
    the one that qualifies. Never point this at a directory holding authored
    work (see :func:`self_ignore_files` for the mixed case), and note that
    ``analysis/`` does NOT qualify despite looking like it does: this module's
    own docstring and the root ``.gitignore`` both say the MixReports there are
    committed on purpose.

    Idempotent, and best-effort: a read-only or missing parent must never take
    down the render or analysis that was actually the point. Skips the write
    when the file already carries the marker, so it does not churn mtimes.
    """
    target = directory / ".gitignore"
    body = _MANAGED_HEADER + "*\n"
    try:
        if target.exists() and target.read_text() == body:
            return
        directory.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    except OSError:
        # Absorbed, not hidden: disk hygiene is never worth failing a capture
        # over, but a silently-unwritten ignore leaves artifacts surfacing as
        # committable with no clue why.
        logger.warning("could not write %s", target, exc_info=True)


def self_ignore_files(directory: Path, filenames: Iterable[str]) -> None:
    """Ignore SPECIFIC filenames inside a directory that also holds authored work.

    The song directory carries `build.py`, `captured_session.json`, `decisions/`
    — all of it committable — alongside tool-written state caches and backups.
    A blanket ``*`` here would ignore the song itself, so this lists the
    generated names and nothing else.

    Merges with any existing entries rather than overwriting: another tool may
    have added its own, and a song dir has several writers. Best-effort and
    idempotent on the same terms as :func:`self_ignore_dir`.
    """
    target = directory / ".gitignore"
    wanted = [n for n in filenames if n]
    if not wanted:
        return
    try:
        existing: list[str] = []
        if target.exists():
            existing = target.read_text().splitlines()
        entries = list(existing)
        added = False
        for name in wanted:
            if name not in entries:
                entries.append(name)
                added = True
        if not added:
            return
        if not existing:
            entries = _MANAGED_HEADER.rstrip("\n").split("\n") + entries
        directory.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(entries).rstrip("\n") + "\n")
    except OSError:
        logger.warning("could not update %s", target, exc_info=True)


# ---------------------------------------------------------------------------
# Audio-clip references — the ONE home for the `clips.audio_file` contract
# ---------------------------------------------------------------------------
#
# Push writes this column and pull reads it back, so the two ends of one round
# trip must agree byte for byte about what a reference means. They were written
# separately and had already drifted: one derived the song directory from
# `PRAGMA database_list`'s FIRST row, the other searched it for the row named
# `main`. Those agree only because sqlite happens to list main first — correct
# by accident on one side, correct by construction on the other. Anything that
# both ends must agree on lives here, once.

def song_dir_for_conn(conn: sqlite3.Connection) -> Path | None:
    """The directory holding this song's ``build.py``, DB and ``assets/``.

    ``clips.audio_file`` is anchored to the song directory, but the pull apply
    layer is handed a connection rather than a path — so the anchor is read off
    the connection's own main database file (``songs/<slug>/<slug>.db`` ->
    ``songs/<slug>/``), the same derivation ``tools/song_context.py`` uses.

    Returns ``None`` for an in-memory database: there is then no anchor, and
    every ingested reference is stored absolute rather than guessed at.
    """
    # PRAGMA database_list rows are (seq, name, file); indexed positionally so
    # the read works under either row factory.
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return Path(row[2]).parent if row[2] else None
    return None


def audio_file_ref(song_dir: Path | None, file_path: str) -> str:
    """Render Live's absolute path into the form ``clips.audio_file`` carries.

    Two forms, and only two: **song-relative POSIX** when the file lives under
    the song directory (the canonical ``assets/...`` reference, which diffs
    identically on every machine), **absolute** for anything else — a sample
    dragged in from the user's own library keeps its absolute path.

    Deliberately NOT :func:`hallucinote.paths.portable_path`. That helper's
    middle form collapses an outside-the-base path to ``~/...``, and the
    resolver this column is read back through — :func:`resolve_audio_path` —
    does not expand ``~`` (only ``resolve_portable_path`` does). A
    ``~``-collapsed reference stored here would resolve as a *relative* path
    under the song directory and fail at the next push.
    """
    p = Path(file_path)
    if song_dir is not None:
        # The song dir and Live's reported path can agree only through a
        # symlink (macOS resolves /tmp to /private/tmp), which is why the
        # containment check is the two-attempt one and not a textual prefix.
        rel = _relative_or_none(p, song_dir)
        if rel is not None:
            return rel
    return p.as_posix()


def same_file_path(a: Path, b: Path) -> bool:
    """Whether two concrete paths name the same file.

    Compared through the filesystem rather than textually: a song directory
    reached through a symlink — ``/tmp`` -> ``/private/tmp`` on macOS is the
    everyday one — spells the same file two ways, and a textual mismatch there
    would read an unchanged clip as a re-pointed one.

    ``resolve()`` touches the filesystem and can raise, so the failure is
    caught here rather than in each caller: the push side guarded it and the
    pull side did not, which is the kind of drift that follows from two copies
    of one comparison.
    """
    if a == b:
        return True
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def same_audio_file(
    song_dir: Path | None, db_ref: Any, live_path: str,
) -> bool:
    """Whether the DB reference and Live's absolute path name the same file.

    Compared as PATHS, never as strings: the DB canonically stores
    ``assets/line.wav`` while Live reports
    ``/.../songs/<slug>/assets/line.wav``, and a textual compare would read
    that as drift and rewrite the portable reference into a machine-absolute
    one on every pull.
    """
    if not db_ref:
        return False
    live = Path(live_path)
    if song_dir is None:
        # No anchor: a relative reference cannot be resolved, so only an
        # absolute one is comparable.
        db_path = Path(str(db_ref))
        if not db_path.is_absolute():
            return False
    else:
        db_path = resolve_audio_path(song_dir, str(db_ref))
    return same_file_path(db_path, live)
