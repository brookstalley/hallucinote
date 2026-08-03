"""Workspace discovery — the project-root contract.

Lets a Hallucinote song live in its **own repo**, outside the engine monorepo,
and still resolve its song directory + DB. The full contract (rationale, the
two-repo topology, the spike evidence) lives in
``.prawduct/artifacts/project-root-contract.md``.

A *workspace* is the directory tree a song (or many) lives in, identified by a
``hallucinote.toml`` marker at its root — discovered by walking up from
``CLAUDE_PROJECT_DIR`` (the dir a plugin-hosted MCP server inherits) or cwd,
exactly like ``.git``.

Resolution precedence for a song's directory (first hit wins):

1. an explicit ``root=`` at the callsite (handled by ``resolve_db_path``;
   e.g. ``build.py`` passes ``root=Path(__file__).parent.parent``)
2. env var ``HALLUCINOTE_SONGS_ROOT`` → ``<env>/<slug>`` (monorepo-style override)
3. a ``hallucinote.toml`` marker (layout-aware: ``monorepo`` nests
   ``songs_root/<slug>``; ``song`` means the marker's dir *is* the song)
4. legacy default ``songs/<slug>`` relative to cwd

Steps 2–4 are purely additive: with no env and no marker (the engine monorepo
today) the legacy default reproduces the historical relative path exactly.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hallucinote.workspace")

# What a song slug may contain. Defined HERE, next to the slug→path resolvers,
# because a slug is only ever meaningful as a path segment: ``resolve_song_dir``
# joins it straight onto a root, and ``pathlib`` join semantics make an ABSOLUTE
# slug replace the root outright (``Path("songs") / "/etc"`` is ``/etc``) while
# ``..`` segments walk out of the songs tree. Any caller that turns a slug into a
# path it will then read — or DELETE under — must run it through
# :func:`validate_slug` first; the character class alone forecloses both escapes.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

MARKER_FILENAME = "hallucinote.toml"
ENV_SONGS_ROOT = "HALLUCINOTE_SONGS_ROOT"
ENV_PROJECT_DIR = "CLAUDE_PROJECT_DIR"

LAYOUT_MONOREPO = "monorepo"  # many songs under songs_root/<slug>/
LAYOUT_SONG = "song"  # the marker's directory IS one song
_VALID_LAYOUTS = (LAYOUT_MONOREPO, LAYOUT_SONG)

_LEGACY_SONGS_ROOT = "songs"


def validate_slug(slug: str) -> None:
    """Raise ``ValueError`` unless ``slug`` is a safe single path segment.

    See :data:`SLUG_RE` for why this is a path-safety guard, not just a
    style rule."""
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(
            f"invalid slug {slug!r}: must match [a-z0-9][a-z0-9_-]* "
            "(lowercase letters, digits, hyphens, underscores; no leading "
            "hyphen or underscore; no uppercase, no spaces, no dots)"
        )


@dataclass(frozen=True)
class Workspace:
    """A resolved workspace marker.

    ``root`` is the directory holding ``hallucinote.toml``. ``songs_root`` is
    relative to ``root`` (monorepo only; ``"."`` for a single-song repo).
    ``slug`` is the song's slug — required for ``layout = "song"`` so the
    single-song repo knows which song it is, ``None`` for a monorepo.
    """

    root: Path
    layout: str
    songs_root: str
    slug: str | None

    def song_dir(self, slug: str) -> Path:
        """Directory holding ``slug``'s ``build.py`` + DB under this workspace."""
        if self.layout == LAYOUT_SONG:
            return self.root
        return self.root / self.songs_root / slug


def _candidate_start(start: Path | str | None) -> Path:
    """Where to begin the upward marker search."""
    if start is not None:
        return Path(start)
    env = os.environ.get(ENV_PROJECT_DIR)
    if env:
        return Path(env)
    return Path.cwd()


def _load_marker(marker: Path) -> dict | None:
    """Parse a ``hallucinote.toml`` marker, or ``None`` if it can't be read.

    The TOML parser is imported lazily so the engine never hard-fails at
    import time on Python < 3.11 without ``tomli`` — a missing parser degrades
    to "no marker" (the caller falls through to env/legacy) rather than raising.
    ``tomli`` is a declared dependency on < 3.11 so this path is rare.
    """
    try:
        import tomllib  # type: ignore[import-not-found]  # py3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            logger.warning(
                "no TOML parser (tomllib/tomli) available; ignoring %s — "
                "install `tomli` on Python < 3.11", marker,
            )
            return None
    try:
        return tomllib.loads(marker.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("failed to read/parse %s: %s", marker, exc)
        return None


def _workspace_from_marker(root: Path, marker: Path) -> Workspace | None:
    data = _load_marker(marker)
    if data is None:
        return None
    ws = data.get("workspace")
    if not isinstance(ws, dict):
        ws = data  # tolerate keys declared at the top level
    layout = str(ws.get("layout", LAYOUT_MONOREPO))
    if layout not in _VALID_LAYOUTS:
        logger.warning(
            "%s declares unknown layout=%r; treating as %r",
            marker, layout, LAYOUT_MONOREPO,
        )
        layout = LAYOUT_MONOREPO
    slug = ws.get("slug")
    slug = str(slug) if slug else None
    if layout == LAYOUT_SONG:
        return Workspace(root=root, layout=layout, songs_root=".", slug=slug)
    songs_root = str(ws.get("songs_root", _LEGACY_SONGS_ROOT))
    return Workspace(root=root, layout=layout, songs_root=songs_root, slug=slug)


def find_workspace(start: Path | str | None = None) -> Workspace | None:
    """Walk up from ``start`` (or ``CLAUDE_PROJECT_DIR`` / cwd) for a marker.

    Returns the first ``hallucinote.toml`` workspace found, or ``None`` if the
    search reaches the filesystem root without one.
    """
    here = _candidate_start(start).resolve()
    for d in (here, *here.parents):
        marker = d / MARKER_FILENAME
        if marker.is_file():
            ws = _workspace_from_marker(d, marker)
            if ws is not None:
                return ws
    return None


def resolve_song_dir(slug: str, *, start: Path | str | None = None) -> Path:
    """Resolve the directory holding a song's ``build.py`` + DB.

    Applies precedence steps 2–4 (the explicit-``root`` step belongs to the
    caller). With no env var and no marker this returns the legacy
    ``songs/<slug>`` relative path, preserving historical behavior.
    """
    env = os.environ.get(ENV_SONGS_ROOT)
    if env:
        return Path(env) / slug
    ws = find_workspace(start)
    if ws is not None:
        return ws.song_dir(slug)
    return Path(_LEGACY_SONGS_ROOT) / slug
