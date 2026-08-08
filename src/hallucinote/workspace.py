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
3. a ``hallucinote.toml`` marker found by walking **up** (layout-aware:
   ``monorepo`` nests ``songs_root/<slug>``; ``song`` means the marker's dir
   *is* the song)
4. the workspace that actually **holds this slug**, among the markers found by
   a bounded descent below the start directory (:func:`find_workspaces_below`)
   and among the start directory's **sibling** workspaces
   (:func:`find_workspaces_beside`) — accepted only when exactly one holds it
5. the sole ``hallucinote.toml`` marker found by the bounded descent, when
   nothing holds the slug yet (the not-yet-created song: ``/song-new``
   scaffolding into the one workspace this session can see)
6. legacy default ``songs/<slug>`` relative to cwd

Steps 2–6 are purely additive: with no env and no marker anywhere the legacy
default reproduces the historical relative path exactly.

**Why steps 4–5 exist.** The start directory is ``CLAUDE_PROJECT_DIR`` / cwd —
never the song being resolved — so a workspace that lives *below* the project
directory (the in-repo ``examples/`` demo workspace; a user whose editor is
rooted one level above their songs repo) is invisible to the upward walk. The
old behavior was to fall through to the legacy rung and hand back
``songs/<slug>`` — a path that names nothing. That was silent, and callers
treat the answer as authoritative: a render created the phantom tree and wrote
gigabytes of WAVs into it, and analysis then reported "slug doesn't name a
built song" for a song that was built all along.

**Why step 4 is slug-aware, and why it comes before step 5.** Discovery alone
answers *"which workspace is near me?"*, which is the wrong question: the
framework repo ships a demo workspace at ``examples/``, so a session rooted at
the framework repo found exactly one marker below, took it unambiguously, and
resolved **every** slug into the demo workspace — including songs living in a
separate songs repo, which is the supported two-repo topology. A single
non-ambiguous candidate is not the same as a *correct* one. Step 4 asks the
right question — *"which workspace HOLDS this song?"* — and that also reaches
the sibling songs repo (``~/src/hallucinote`` + ``~/src/hallucinote-songs``)
that neither the up-walk nor the descent can see. Step 5 keeps the old
behavior for the case where no workspace can hold the song yet because it does
not exist: scaffolding a new song still lands in the session's own workspace.
When more than one workspace holds the slug nothing is picked;
:func:`explain_unresolved_song` names the candidates instead.
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

# --- bounded descent (precedence step 4) ----------------------------------
# How far BELOW the start directory to look for a marker. 2 covers the shapes
# that actually occur — ``<repo>/examples/`` (depth 1) and an editor rooted a
# level or two above a songs repo (``~/src/music/my-songs/``) — while keeping
# the scan to a handful of ``scandir`` calls. Deeper nesting is not guessed at:
# it fails loud through ``explain_unresolved_song`` instead.
MAX_DESCEND_DEPTH = 2
# Hard ceiling on directories visited, so the descent can never turn a resolve
# into a filesystem crawl if someone points a session at a huge tree.
_DESCEND_DIR_BUDGET = 500
# Directory names never worth descending into: VCS, caches, build output, and
# dependency trees. Any name starting with "." is skipped too (see below).
_DESCEND_SKIP_NAMES = frozenset({
    "node_modules", "__pycache__", "venv", "site-packages",
    "build", "dist", "target", "vendor",
})


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


def find_workspace_above(start: Path | str | None = None) -> Workspace | None:
    """Walk **up** from ``start`` (or ``CLAUDE_PROJECT_DIR`` / cwd) for a marker.

    Returns the first ``hallucinote.toml`` workspace found, or ``None`` if the
    search reaches the filesystem root without one. This is precedence step 3
    on its own — no descent, no fallbacks.
    """
    here = _candidate_start(start).resolve()
    for d in (here, *here.parents):
        marker = d / MARKER_FILENAME
        if marker.is_file():
            ws = _workspace_from_marker(d, marker)
            if ws is not None:
                return ws
    return None


def find_workspaces_below(
    start: Path | str | None = None, *, max_depth: int = MAX_DESCEND_DEPTH,
) -> list[Workspace]:
    """Every workspace whose marker sits at most ``max_depth`` levels BELOW
    ``start`` — the descent half of discovery (precedence step 4).

    Breadth-first, so shallower workspaces come first, and a directory that is
    itself a workspace is never descended into (its subtree belongs to it — a
    nested marker would be that workspace's own business, not a sibling
    candidate). Hidden dirs, VCS/cache/build/dependency dirs and anything past
    :data:`_DESCEND_DIR_BUDGET` are skipped: discovery must stay cheap enough
    to sit on the resolve path.

    Returns a *list* rather than a single answer on purpose. Descent can be
    genuinely ambiguous (a parent directory holding three song repos), and
    guessing there would recreate the silent-wrong-answer bug in a new place;
    callers decide, and :func:`explain_unresolved_song` names the candidates
    when nobody can.
    """
    root = _candidate_start(start).resolve()
    if not root.is_dir():
        return []
    found: list[Workspace] = []
    frontier = [root]
    budget = _DESCEND_DIR_BUDGET
    for _depth in range(max_depth):
        if not frontier or budget <= 0:
            break
        nxt: list[Path] = []
        for parent in frontier:
            try:
                children = sorted(p for p in parent.iterdir() if p.is_dir())
            except OSError:  # unreadable dir — not fatal to discovery
                continue
            for child in children:
                if budget <= 0:
                    break
                budget -= 1
                name = child.name
                if name.startswith(".") or name in _DESCEND_SKIP_NAMES:
                    continue
                marker = child / MARKER_FILENAME
                if marker.is_file():
                    ws = _workspace_from_marker(child, marker)
                    if ws is not None:
                        found.append(ws)
                        continue  # a workspace owns its subtree; don't descend
                nxt.append(child)
        frontier = nxt
    return found


def find_workspaces_beside(start: Path | str | None = None) -> list[Workspace]:
    """Every workspace whose marker sits in a **sibling** directory of ``start``.

    The supported two-repo topology puts the engine and the songs side by side
    (``~/src/hallucinote`` + ``~/src/hallucinote-songs``), and a session rooted
    at either one cannot see the other: the songs repo is not above the
    framework repo, and it is not below it. Neither
    :func:`find_workspace_above` nor :func:`find_workspaces_below` can reach
    it, so without this rung the topology only works if the operator sets
    ``$HALLUCINOTE_SONGS_ROOT`` by hand.

    Deliberately **one level only** — the immediate children of ``start``'s
    parent, a single ``iterdir`` — because this rung runs on the resolve path
    and a sideways *descent* would turn every unresolved slug into a crawl of
    the operator's whole source tree. A songs repo parked deeper than that is
    what ``$HALLUCINOTE_SONGS_ROOT`` is for, and
    :func:`explain_unresolved_song` says so.

    Like :func:`find_workspaces_below` this returns a *list*: siblings are
    genuinely ambiguous (two songs repos, one slug) and the caller decides.
    ``start`` itself is never included, and the answer is only ever consulted
    slug-gated (precedence step 4) — a sibling workspace never wins on
    proximity, only on actually holding the song.
    """
    here = _candidate_start(start).resolve()
    parent = here.parent
    if parent == here:  # filesystem root has no siblings
        return []
    try:
        children = sorted(p for p in parent.iterdir() if p.is_dir())
    except OSError:
        return []
    found: list[Workspace] = []
    budget = _DESCEND_DIR_BUDGET
    for child in children:
        if budget <= 0:
            break
        budget -= 1
        if child == here:
            continue
        name = child.name
        if name.startswith(".") or name in _DESCEND_SKIP_NAMES:
            continue
        marker = child / MARKER_FILENAME
        if marker.is_file():
            ws = _workspace_from_marker(child, marker)
            if ws is not None:
                found.append(ws)
    return found


def _holds_song(ws: Workspace, slug: str) -> bool:
    """Whether ``ws`` actually carries a built ``slug`` (not merely a name).

    The predicate behind precedence step 4. Reuses :func:`_looks_built`, so a
    directory holding only the residue of a misresolved render — a bare
    ``captures/`` — does not qualify, and the wreckage of this very bug can
    never vote itself into being the answer.
    """
    return _looks_built(ws.song_dir(slug))


def find_workspace(
    start: Path | str | None = None, *, descend: bool = False,
) -> Workspace | None:
    """The workspace governing ``start`` — up first, then optionally down.

    ``descend=False`` (the default) is the historical containment question
    *"which workspace am I inside?"*, and it is the right question for
    ``hallucinote init-workspace``'s refuse-inside-an-existing-workspace guard:
    a directory that merely *contains* a workspace is not itself one.

    ``descend=True`` asks the resolution question — *"which workspace do the
    songs of this session live in?"* — and falls back to a bounded descent
    (:func:`find_workspaces_below`) when the upward walk finds nothing. An
    ambiguous descent (more than one workspace below) returns ``None`` rather
    than picking: the caller falls through to the legacy default and the
    failure surfaces with the candidates named.
    """
    ws = find_workspace_above(start)
    if ws is not None or not descend:
        return ws
    below = find_workspaces_below(start)
    if len(below) == 1:
        return below[0]
    if below:
        logger.warning(
            "%d workspaces found below %s (%s); none chosen — name one with "
            "$%s, or run from inside the one you mean",
            len(below), _candidate_start(start),
            ", ".join(str(w.root) for w in below), ENV_SONGS_ROOT,
        )
    return None


# Where a resolved song dir came from, for diagnostics. Values are stable
# enough to assert on in tests and to branch remediation advice on.
SOURCE_ENV = "env"
SOURCE_MARKER_ABOVE = "marker-above"
SOURCE_MARKER_BELOW = "marker-below"
#: A sibling workspace that actually holds the slug (precedence step 4).
SOURCE_MARKER_BESIDE = "marker-beside"
SOURCE_LEGACY = "legacy"


@dataclass(frozen=True)
class SongDirResolution:
    """A resolved song dir plus *how* it was resolved.

    ``resolve_song_dir`` returns only the path, which is all a caller needs
    when the answer is right. When it is wrong the path alone is unreadable —
    "songs/foo" says nothing about whether a marker was found and rejected or
    never looked for. This carries the provenance so an error message can say
    which.
    """

    song_dir: Path
    source: str
    workspace: Workspace | None = None
    #: Workspaces found below the start dir — populated only when the descent
    #: was ambiguous (and therefore declined).
    ambiguous_below: tuple[Workspace, ...] = ()
    #: Workspaces that each hold this slug — populated only when MORE THAN ONE
    #: does, so no holder could be chosen (precedence step 4 declined).
    ambiguous_holders: tuple[Workspace, ...] = ()


def resolve_song_dir_explained(
    slug: str, *, start: Path | str | None = None,
) -> SongDirResolution:
    """:func:`resolve_song_dir` plus the provenance of its answer.

    Implements precedence steps 2–6 (see the module docstring). The ordering
    that matters: an explicit statement (env, then the workspace the session is
    *inside*) beats inference, and inference asks *"who holds this song?"*
    before it settles for *"who is nearby?"* — so a demo workspace that happens
    to sit below the session root can no longer capture a slug that belongs to
    a different workspace entirely.
    """
    env = os.environ.get(ENV_SONGS_ROOT)
    if env:
        return SongDirResolution(Path(env) / slug, SOURCE_ENV)
    above = find_workspace_above(start)
    if above is not None:
        return SongDirResolution(above.song_dir(slug), SOURCE_MARKER_ABOVE, above)

    # Step 4 — the workspace that actually HOLDS the slug. Below beats beside:
    # a workspace inside the session's own tree is the better answer when both
    # carry the song, and only then is `beside` consulted at all.
    below = find_workspaces_below(start)
    holders = [ws for ws in below if _holds_song(ws, slug)]
    source = SOURCE_MARKER_BELOW
    if not holders:
        holders = [ws for ws in find_workspaces_beside(start) if _holds_song(ws, slug)]
        source = SOURCE_MARKER_BESIDE
    if len(holders) == 1:
        return SongDirResolution(holders[0].song_dir(slug), source, holders[0])
    if holders:
        # Two workspaces both carry this slug. Picking one would be the same
        # confident-but-wrong answer this precedence exists to prevent, so
        # decline and let `explain_unresolved_song` name them.
        logger.warning(
            "%d workspaces hold a song %r (%s); none chosen — name one with "
            "$%s, or run from inside the one you mean",
            len(holders), slug, ", ".join(str(w.root) for w in holders),
            ENV_SONGS_ROOT,
        )
        return SongDirResolution(
            Path(_LEGACY_SONGS_ROOT) / slug, SOURCE_LEGACY,
            ambiguous_below=tuple(below),
            ambiguous_holders=tuple(holders),
        )

    # Step 5 — nothing holds the slug. It may simply not exist yet, so a lone
    # workspace below the session root is still the right place to scaffold it.
    if len(below) == 1:
        return SongDirResolution(
            below[0].song_dir(slug), SOURCE_MARKER_BELOW, below[0]
        )
    if below:
        logger.warning(
            "%d workspaces found below %s (%s); falling back to the legacy "
            "%s/%s — name one with $%s, or run from inside the one you mean",
            len(below), _candidate_start(start),
            ", ".join(str(w.root) for w in below),
            _LEGACY_SONGS_ROOT, slug, ENV_SONGS_ROOT,
        )
    return SongDirResolution(
        Path(_LEGACY_SONGS_ROOT) / slug, SOURCE_LEGACY,
        ambiguous_below=tuple(below),
    )


def resolve_song_dir(slug: str, *, start: Path | str | None = None) -> Path:
    """Resolve the directory holding a song's ``build.py`` + DB.

    Applies precedence steps 2–5 (the explicit-``root`` step belongs to the
    caller). With no env var and no marker anywhere this returns the legacy
    ``songs/<slug>`` relative path, preserving historical behavior.
    """
    return resolve_song_dir_explained(slug, start=start).song_dir


def _looks_built(song_dir: Path) -> bool:
    """Whether ``song_dir`` holds an actual song rather than just a name.

    A song dir earns the description by carrying its authorship (``build.py``)
    or its DB. Deliberately NOT satisfied by a bare ``captures/`` — that is
    exactly the residue a misresolved render leaves behind, and treating it as
    a song would let the wreckage of the bug masquerade as the song it
    displaced.
    """
    if not song_dir.is_dir():
        return False
    return (song_dir / "build.py").is_file() or any(song_dir.glob("*.db"))


def find_song_elsewhere(
    slug: str, *, start: Path | str | None = None,
) -> list[Path]:
    """Directories where ``slug`` IS built, other than the resolved one.

    Consulted before telling an operator to build a song: advising
    ``build.py --reset`` for a song that already exists somewhere else invites
    them to scaffold a duplicate over work that was never missing.
    """
    resolved = resolve_song_dir_explained(slug, start=start).song_dir
    resolved_abs = (_candidate_start(start).resolve() / resolved).resolve()
    seen: list[Path] = []
    candidates: list[Path] = [
        _candidate_start(start).resolve() / _LEGACY_SONGS_ROOT / slug
    ]
    candidates += [ws.song_dir(slug) for ws in find_workspaces_below(start)]
    candidates += [ws.song_dir(slug) for ws in find_workspaces_beside(start)]
    above = find_workspace_above(start)
    if above is not None:
        candidates.append(above.song_dir(slug))
    for cand in candidates:
        cand = cand.resolve()
        if cand == resolved_abs or cand in seen:
            continue
        if _looks_built(cand):
            seen.append(cand)
    return seen


def explain_unresolved_song(
    slug: str, *, start: Path | str | None = None,
) -> str:
    """A teaching sentence for "this slug didn't resolve to a built song".

    Distinguishes the failures a bare "doesn't name a built song" runs together
    — the song dir resolves but was never built / resolved into a workspace
    that doesn't hold it / resolved by the legacy fallback because no marker was
    found / the song genuinely does not exist — and, when the song IS built
    somewhere else, says so and where instead of recommending a rebuild.

    **It also re-checks the caller's premise.** Callers reach this after their
    own "is it there?" test failed, and that test can be wrong (a stale path, a
    per-branch DB name, a race with a build). Without the re-check the absence
    branches would run on a song that is plainly present and emit a sentence
    that contradicts itself — *"has no song 'x' — songs it does have: x"* — the
    same misleading-error failure this whole module exists to eliminate. So the
    resolvable cases are answered FIRST and the absence wording is unreachable
    unless the song dir really is absent. ``_sibling_slugs`` drops ``slug`` too:
    one guard is a branch that can drift, two make the contradiction structural.
    """
    res = resolve_song_dir_explained(slug, start=start)
    where = _candidate_start(start).resolve()

    # Premise re-check, before any wording that asserts absence.
    if res.song_dir.is_dir():
        dbs = sorted(p.name for p in res.song_dir.glob("*.db"))
        if dbs:
            return (
                f"{slug!r} DOES resolve, to a built song at {res.song_dir} "
                f"(DB: {', '.join(dbs)}) — nothing is missing at the resolution "
                f"layer, so a caller reporting it absent checked a different "
                f"path than the one that exists. The usual cause is the "
                f"per-branch DB filename (`<slug>-<branch>.db`, `/`→`--`): a "
                f"check for a bare `{slug}.db`, or for another branch's, misses "
                f"the file sitting right there. Compare against {res.song_dir}."
            )
        if (res.song_dir / "build.py").is_file():
            return (
                f"the song dir for {slug!r} exists at {res.song_dir} and holds "
                f"its build.py, but no DB — it is scaffolded, not yet built. "
                f"`python3 {res.song_dir / 'build.py'} --reset` builds it."
            )

    elsewhere = find_song_elsewhere(slug, start=start)

    if res.source == SOURCE_ENV:
        lead = (
            f"${ENV_SONGS_ROOT}={os.environ.get(ENV_SONGS_ROOT)!r} resolves "
            f"{slug!r} to {res.song_dir}, which holds no song"
        )
    elif res.ambiguous_holders:
        roots = ", ".join(str(w.root) for w in res.ambiguous_holders)
        lead = (
            f"{len(res.ambiguous_holders)} workspaces ({roots}) each hold a "
            f"song {slug!r}, so the choice is ambiguous and none was made"
        )
    elif res.source in (
        SOURCE_MARKER_ABOVE, SOURCE_MARKER_BELOW, SOURCE_MARKER_BESIDE,
    ):
        assert res.workspace is not None
        root = res.workspace.root
        known = _sibling_slugs(res.workspace, exclude=slug)
        lead = (
            f"the workspace at {root} (marker {root / MARKER_FILENAME}) has no "
            f"song {slug!r}"
        )
        if known:
            lead += f" — songs it does have: {', '.join(known)}"
    else:
        lead = (
            f"no {MARKER_FILENAME} workspace marker was found at or above "
            f"{where}, so {slug!r} fell back to the legacy "
            f"{_LEGACY_SONGS_ROOT}/{slug} path (which holds no song)"
        )
        if res.ambiguous_below:
            roots = ", ".join(str(w.root) for w in res.ambiguous_below)
            lead += (
                f"; {len(res.ambiguous_below)} workspaces were found below "
                f"{where} ({roots}) and none was chosen because the choice is "
                f"ambiguous"
            )

    if elsewhere:
        found = ", ".join(str(p) for p in elsewhere)
        return (
            f"{lead}. {slug!r} IS built at {found} — that workspace is not the "
            f"one this process resolves. Do NOT rebuild it: run from inside "
            f"that workspace, or set ${ENV_SONGS_ROOT} to the directory holding "
            f"the song dirs. (See .prawduct/artifacts/project-root-contract.md.)"
        )
    return (
        f"{lead}. If {slug!r} exists in a workspace elsewhere, run from inside "
        f"it or set ${ENV_SONGS_ROOT} to the directory holding the song dirs; "
        f"if it genuinely doesn't exist yet, `python3 {res.song_dir}/build.py "
        f"--reset` creates it."
    )


def _sibling_slugs(
    ws: Workspace, *, exclude: str | None = None, limit: int = 12,
) -> list[str]:
    """Song slugs already present in ``ws`` — the "did you mean" list.

    ``exclude`` drops the slug being diagnosed. The caller's branch logic should
    already make that impossible (a present slug never reaches an absence
    sentence), but "should" is what produced *"has no song 'x' — songs it does
    have: x"*. Enforcing it here means no future caller can reintroduce it.
    """
    if ws.layout == LAYOUT_SONG:
        return [ws.slug] if ws.slug and ws.slug != exclude else []
    root = ws.root / ws.songs_root
    try:
        names = sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name != exclude
            and _looks_built(p)
        )
    except OSError:
        return []
    return names[:limit]
