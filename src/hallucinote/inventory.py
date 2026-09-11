"""Machine-local browser inventory cache.

Authoring a portable ``preset_query`` by name normally needs Live running,
because Live's content browser is only queryable live. This module is the
offline side: a *cache* of the installed loadable content, so a composer can
pick built-in kits/instruments by name and author a ``preset_query`` WITHOUT
Live open, and so the push-then-recapture loop disappears.

Design constraints (see ``.prawduct/artifacts/build-plan.md``):

- **Machine-specific, user-global, never shared.** The cache lives at
  ``~/.hallucinote/inventory/`` — a property of (this machine, this Live
  install), not of any repo. It is outside every repo tree, so sharing a repo
  carries ZERO assumptions about a teammate's installed library. Nothing to
  gitignore — share-safety is structural.

- **A cache, not a durable index.** It goes stale (you install a pack, a
  preset moves) and must be refreshed deliberately (:func:`refresh`, which
  needs Live). Staleness is *advisory, never blocking*: offline picks warn
  with the cache's age; push-time resolution stays the source of truth — if
  the cache lied (content uninstalled), push fails loudly in Live where it can
  confirm. So a stale cache can only ever surface as a loud push-time miss,
  never a silent wrong load.

- **Resolves identically to push.** Offline resolution (:func:`find`, via
  :func:`hallucinote.preset_query.resolve_query`) uses the SAME matcher the
  push-time resolver uses, and the cache is walked to the SAME depth
  (:data:`hallucinote.preset_query.MIN_WALK_DEPTH`). Both are pinned by
  lock-tests in ``tests/unit/sync/test_compat.py``.

- **Scale.** A pack-heavy install is tens of thousands of loadables; a single
  instrument can carry thousands of presets. The cache is built one root at a
  time (the ``ableton_browser(action='inventory')`` MCP action caps each
  response under the 16 MiB wire frame and bounds the main-thread walk), and
  ``samples`` — the giant root least relevant to instrument/kit picking — is
  excluded by default (resolvable live at push if ever referenced). Roots that
  exceed the cap are recorded as *partially covered*, never silently truncated.
"""
from __future__ import annotations

import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hallucinote.preset_query import BROWSER_ROOTS, MIN_WALK_DEPTH, resolve_query

# Cache format version — bump when the on-disk shape changes so a stale-shape
# cache can be detected and re-built rather than mis-read.
SCHEMA_VERSION = 1

# Roots cached by default. ``samples`` is excluded — it is the largest root
# (thousands of raw one-shots/loops) and the least relevant to picking an
# instrument / effect / drum kit by name. Excluded roots resolve live at push;
# the exclusion is recorded in the cache header (``roots_excluded``) and
# surfaced by :func:`find`, never silent.
DEFAULT_CACHED_ROOTS: tuple[str, ...] = (
    "instruments", "audio_effects", "midi_effects", "drums",
    "plugins", "user_library", "packs",
)

# A large root walk runs on Live's main thread and can exceed the client's 15 s
# default; give the inventory calls a generous ceiling.
_INVENTORY_READ_TIMEOUT = 180.0

# How deep to subdivide a root that exceeds the per-call breadth cap before
# giving up and recording the branch as partial. One level of subdivision
# (per top-level child folder) clears all but pathological libraries.
_MAX_SUBDIVIDE_LEVELS = 1


def cache_path() -> Path:
    """Absolute path to the inventory cache file for this machine."""
    return Path.home() / ".hallucinote" / "inventory" / "cache.json"


# --- read side (offline) ----------------------------------------------------


def read_cache(path: Path | None = None) -> dict | None:
    """Load the inventory cache, or ``None`` if it doesn't exist yet.

    Raises ``ValueError`` on a corrupt or wrong-schema file — a loud failure
    that tells the caller to refresh, rather than a silent empty result that
    would read as "nothing installed".
    """
    p = path or cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"inventory cache at {p} is unreadable ({exc}); refresh it with "
            '`"<python>" -m hallucinote.cli inventory refresh`'
        ) from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"inventory cache at {p} has schema_version "
            f"{data.get('schema_version') if isinstance(data, dict) else '?'} "
            f"(expected {SCHEMA_VERSION}); refresh it with "
            '`"<python>" -m hallucinote.cli inventory refresh`'
        )
    return data


def cache_age_days(cache: dict, *, now: datetime | None = None) -> float | None:
    """Age of the cache in days from ``captured_at``; ``None`` if unparseable."""
    captured = cache.get("captured_at")
    if not isinstance(captured, str):
        return None
    try:
        ts = datetime.fromisoformat(captured)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return (current - ts).total_seconds() / 86400.0


def find(cache: dict, query: dict | str) -> dict:
    """Resolve a ``preset_query`` against the cache, returning the single
    matching entry (``{root, path, name, uri, is_loadable}``).

    Delegates matching to :func:`hallucinote.preset_query.resolve_query` — the
    same strict single-match semantics the push-time loader enforces — so an
    offline pick resolves identically at push.

    Raises ``ValueError`` (the resolver's teaching errors) on 0 / 2+ matches,
    OR if the query targets a root the cache doesn't fully cover — the latter
    is surfaced explicitly so a miss against an excluded/partial root is never
    mistaken for "not installed".
    """
    from hallucinote.preset_query import normalize
    q = normalize(query)
    root = q.get("root", "instruments")
    if root in set(cache.get("roots_excluded", [])):
        raise ValueError(
            f"preset_query.root={root!r} is not cached (excluded from the "
            f"machine inventory cache: {sorted(cache.get('roots_excluded', []))}). "
            "Pick from a cached root, or resolve live by pushing with Live open."
        )
    # A root in roots_partial is resolved normally — the cache HAS some of it.
    # But a miss there may be a coverage gap, not "not installed" (the very
    # conflation the partial-tracking exists to avoid), so a 0-match against a
    # partial root is re-raised with that context. Ambiguity (2+) errors pass
    # through unchanged — that's not a coverage problem.
    is_partial = root in set(cache.get("roots_partial", []))
    try:
        return resolve_query(q, cache.get("entries", []))
    except ValueError as exc:
        if is_partial and "no loadable matches" in str(exc):
            raise ValueError(
                f"{exc} NOTE: root {root!r} is only PARTIALLY cached (it "
                "exceeded the inventory breadth cap) — this miss may be a "
                "coverage gap, not 'not installed'. Refresh with Live open, "
                "or resolve live at push."
            ) from None
        raise


# --- write side (needs Live) ------------------------------------------------


def _resolve_send_fn() -> Callable:
    """Lazy resolver for the MCP client send fn (mirrors push_cli/push_execute
    so importing this module never requires ``hallucinote_mcp`` to be
    installed — only :func:`refresh` does)."""
    # Escalation-aware: a call that outruns Live's main-thread ceiling comes
    # back ok=True carrying a job handle, and reading that as the call's result
    # books work that has not landed. Resolving through the shared helper is
    # what makes that true here without this module knowing the contract.
    from hallucinote.sync.live_escalation import (
        resolve_client_send,
        stderr_progress,
    )

    return resolve_client_send(
        progress_fn=stderr_progress,
    )


def _inventory_call(
    send_fn: Callable, root: str, path_prefix: list[str] | None, read_timeout: float,
) -> dict:
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]
    params: dict[str, Any] = {"root": root}
    if path_prefix:
        params["path_prefix"] = path_prefix
    resp = send_fn(
        Request(tool="ableton_browser", action="inventory", params=params),
        read_timeout=read_timeout,
    )
    if not getattr(resp, "ok", False):
        raise RuntimeError(
            f"ableton_browser(inventory, root={root!r}, "
            f"path_prefix={path_prefix!r}) failed: "
            f"{getattr(resp, 'error', 'unknown error')}"
        )
    return resp.result


def _tree_children(
    send_fn: Callable, root: str, path_prefix: list[str] | None, read_timeout: float,
) -> list[str]:
    """Top-level child folder names under a scope, for subdividing a too-large
    root. Uses ``at_path`` when a prefix is given, else ``tree`` depth 1."""
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]
    if path_prefix:
        resp = send_fn(
            Request(tool="ableton_browser", action="at_path",
                    params={"path": [root, *path_prefix]}),
            read_timeout=read_timeout,
        )
        node = resp.result.get("node", {}) if getattr(resp, "ok", False) else {}
        children = node.get("children", []) or []
    else:
        resp = send_fn(
            Request(tool="ableton_browser", action="tree",
                    params={"root": root, "depth": 1}),
            read_timeout=read_timeout,
        )
        tree = resp.result.get("tree", {}) if getattr(resp, "ok", False) else {}
        children = tree.get("children", []) or []
    return [str(c.get("name", "")) for c in children if c.get("name")]


def _collect_root(
    send_fn: Callable, root: str, read_timeout: float,
) -> tuple[list[dict], list[list[str]], str | None, str | None]:
    """Collect every loadable under ``root``, subdividing on the breadth cap.

    Returns ``(entries, partial_scopes, live_version, live_variant)``.
    ``partial_scopes`` lists any branch still capped after the subdivision
    budget (never silently dropped). Entries are de-duplicated by path so a
    subdivided root and its capped parent partial don't double-count. The
    version stamp is read from the inventory responses (best-effort).
    """
    entries: list[dict] = []
    partial: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    version: dict[str, str | None] = {"v": None, "var": None}

    def _add(es: list[dict]) -> None:
        for e in es:
            key = tuple(e.get("path", []))
            if key not in seen:
                seen.add(key)
                entries.append(e)

    def _walk(prefix: list[str] | None, level: int) -> None:
        result = _inventory_call(send_fn, root, prefix, read_timeout)
        version["v"] = version["v"] or result.get("live_version")
        version["var"] = version["var"] or result.get("live_variant")
        if not result.get("truncated"):
            _add(result.get("entries", []))
            return
        # Capped at this scope. Keep what we got, then subdivide if allowed.
        _add(result.get("entries", []))
        if level >= _MAX_SUBDIVIDE_LEVELS:
            partial.append(prefix or [root])
            return
        children = _tree_children(send_fn, root, prefix, read_timeout)
        if not children:
            partial.append(prefix or [root])
            return
        for child in children:
            _walk((prefix or []) + [child], level + 1)

    _walk(None, 0)
    return entries, partial, version["v"], version["var"]


def refresh(
    *,
    roots: tuple[str, ...] = DEFAULT_CACHED_ROOTS,
    send_fn: Callable | None = None,
    path: Path | None = None,
    read_timeout: float = _INVENTORY_READ_TIMEOUT,
    now: datetime | None = None,
) -> dict:
    """Rebuild the machine inventory cache from the live browser and write it.

    Requires Live running (talks to the Remote Script via the MCP client).
    Walks the requested ``roots`` (default :data:`DEFAULT_CACHED_ROOTS` —
    ``samples`` excluded), one root at a time, subdividing any root that
    exceeds the per-call breadth cap. Writes the assembled cache and returns
    it. ``send_fn`` is injectable for tests.
    """
    for r in roots:
        if r not in BROWSER_ROOTS:
            raise ValueError(
                f"root {r!r} not in valid roots {sorted(BROWSER_ROOTS)}"
            )
    send = send_fn or _resolve_send_fn()

    entries: list[dict] = []
    roots_covered: list[str] = []
    roots_partial: list[str] = []
    live_version: str | None = None
    live_variant: str | None = None
    for r in roots:
        root_entries, partial, version, variant = _collect_root(send, r, read_timeout)
        entries.extend(root_entries)
        # First non-empty version stamp wins (it's the same Live for all roots).
        live_version = live_version or version
        live_variant = live_variant or variant
        if partial:
            roots_partial.append(r)
        else:
            roots_covered.append(r)

    excluded = sorted(set(BROWSER_ROOTS) - set(roots))
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    cache = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": stamp,
        "machine_id": socket.gethostname(),
        # Live version + edition (e.g. "12.1.5", "Suite") — a secondary
        # staleness signal: upgrading/switching Live should prompt a refresh.
        # Age (captured_at) is the primary signal.
        "live_version": live_version,
        "live_variant": live_variant,
        "walk_depth": MIN_WALK_DEPTH,
        "roots_covered": roots_covered,
        "roots_partial": roots_partial,
        "roots_excluded": excluded,
        "count": len(entries),
        "entries": entries,
    }

    out = path or cache_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cache, indent=2))
    return cache


def _main(argv: list[str]) -> int:
    if not argv or argv[0] != "refresh":
        print('usage: "<python>" -m hallucinote.cli inventory refresh')
        return 2
    cache = refresh()
    p = cache_path()
    print(
        f"inventory cache written: {p}\n"
        f"  {cache['count']} loadables across {len(cache['roots_covered'])} "
        f"roots ({', '.join(cache['roots_covered'])})"
    )
    if cache["roots_partial"]:
        print(
            f"  PARTIAL coverage (too large for the breadth cap): "
            f"{', '.join(cache['roots_partial'])} — find() warns; push "
            "resolves these live."
        )
    if cache["roots_excluded"]:
        print(f"  excluded (resolve live at push): {', '.join(cache['roots_excluded'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
