"""Path references in persisted artifacts (CLP-AUD1, AUD-PORTPATH).

Two directions of the same rule: **a path that gets written down is
written down portably.** ``clips.audio_file`` stores the reference
exactly as authored — a song-relative POSIX path (canonically under
``assets/``, where AUD-9R3V's recorded takes will also land) or an
absolute path — and :func:`resolve_audio_path` is the single
resolution point (push (CLP-AUD2) and analysis ingest resolve through
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

from pathlib import Path, PurePosixPath


def resolve_audio_path(song_dir: str | Path, ref: str) -> Path:
    """Resolve a ``clips.audio_file`` reference against a song directory.

    Relative refs are POSIX-separated by contract and resolve under
    ``song_dir`` — the directory containing the song's ``build.py``;
    the helper takes it as an explicit argument so the policy stays
    caller-owned. Absolute refs pass through unchanged (stored
    as-given; the push-time existence check is CLP-AUD2 scope).
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
