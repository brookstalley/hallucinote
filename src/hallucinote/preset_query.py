"""Canonical preset_query shape + path-shape parser.

Arc 3 / C2. The structured ``{root, pattern, path_prefix}`` dict is the
DB-canonical form for a portable, cross-machine preset selection; the
push planner and the MCP loader both consume the dict. Authoring is
verbose in that form, so this module ships the syntactic sugar:

    "Drums/Kit-Core 909"  →  {"root": "drums", "pattern": "Kit-Core 909"}

The path-shape never enters the DB or downstream consumers. Only
:func:`hallucinote.db.mutations.create_device` accepts ``str``; on
write it normalizes to canonical dict, which then JSON-serializes to
the ``devices.preset_query`` column.

Kept at the top of the package (no ``db``/``sync`` dependency) so both
layers can import the constant + parser without inverting the
``db → sync`` direction.
"""
from __future__ import annotations

import fnmatch
import re


# Browser roots accepted by ``ableton_device(action='load', preset_query=...)``.
# MUST agree with the MCP server's ``hallucinote_mcp.actions.browser._ROOTS``
# enum — the lock-test in tests/unit/sync/test_compat.py
# (``test_valid_browser_roots_lock_matches_mcp_side``) pins the two sides.
BROWSER_ROOTS: frozenset[str] = frozenset({
    "instruments", "audio_effects", "midi_effects", "drums", "plugins",
    "samples", "user_library", "packs",
})


def parse_path_shape(path: str) -> dict:
    """Parse a path-shape preset_query string into the canonical dict.

    Format: ``<root>/[<segment>/...]<pattern>``. The last segment is
    always the pattern; everything between the root and the last
    segment is ``path_prefix``.

    Root canonicalization is intentional ergonomics for authoring:
    case-insensitive, and ``" "`` is treated as ``"_"`` so authors
    can write either ``"Audio Effects/Hall"`` or
    ``"audio_effects/Hall"`` interchangeably. Path-prefix and pattern
    segments are preserved verbatim — Live's browser matches segment
    names literally, so we must not silently mangle them.

    Raises ``ValueError`` (matching the existing dict-validation
    contract callers handle) on: single segment (ambiguous between
    root and pattern), empty pattern segment, unknown root. Mode /
    case_sensitive are not surfacable through path-shape — authors
    who need those pass a dict.
    """
    if not isinstance(path, str):
        raise ValueError(
            f"preset_query path must be a string, got {type(path).__name__}"
        )
    segments = path.split("/")
    if len(segments) < 2:
        raise ValueError(
            f"preset_query path {path!r} needs at least <root>/<pattern>; "
            "got a single segment (the root must be one of "
            f"{sorted(BROWSER_ROOTS)})"
        )
    root_raw = segments[0].strip().lower().replace(" ", "_")
    if root_raw not in BROWSER_ROOTS:
        raise ValueError(
            f"preset_query path root {segments[0]!r} not in valid roots "
            f"{sorted(BROWSER_ROOTS)} (case-insensitive; spaces and "
            "underscores are equivalent)"
        )
    pattern = segments[-1]
    if not pattern.strip():
        raise ValueError(
            f"preset_query path {path!r} has empty pattern (last segment); "
            "the pattern must be non-empty"
        )
    path_prefix = list(segments[1:-1])
    # Arc 5 / P5: reject empty interior segments at the authoring boundary.
    # ``"Drums//Kit"`` previously yielded ``path_prefix=['']`` — Live's
    # browser can't match an empty segment, so it surfaced as
    # ``kind_unresolvable`` at probe time. Failing here makes the
    # diagnostic surface AT the typo, not five layers down.
    for seg in path_prefix:
        if not seg.strip():
            raise ValueError(
                f"preset_query path {path!r} has an empty interior segment; "
                "double-slashes and whitespace-only segments are rejected — "
                "use a single '/' between non-empty segments"
            )
    out: dict = {"root": root_raw, "pattern": pattern}
    if path_prefix:
        out["path_prefix"] = path_prefix
    return out


def normalize(preset_query):
    """Accept either canonical dict or path-shape string; return canonical
    dict (or ``None`` if input is ``None``).

    Convenience for callers that want to support both shapes without
    type-switching. Strings flow through :func:`parse_path_shape`;
    dicts pass through unchanged.
    """
    if preset_query is None:
        return None
    if isinstance(preset_query, str):
        return parse_path_shape(preset_query)
    if isinstance(preset_query, dict):
        return preset_query
    raise ValueError(
        f"preset_query must be a dict, str, or None — got "
        f"{type(preset_query).__name__}"
    )


# --- Offline resolution -----------------------------------------------------
#
# A1 / offline-browser-cache. Authoring a portable preset_query by name
# normally requires Live running, because the browser is live-queried and the
# push-time resolver (hallucinote_mcp.handlers.device._resolve_preset_query)
# walks the live browser. The offline path resolves the SAME query against a
# machine-local inventory cache (see hallucinote.inventory). To guarantee an
# offline-authored query resolves IDENTICALLY when Live runs at push, the two
# sides must agree on (a) the name matcher and (b) how deep the inventory was
# walked. Both are pinned by lock-tests in tests/unit/sync/test_compat.py.
#
# The MCP handlers run inside Live's Remote Script Python, which does not have
# this (domain) package installed — so they cannot import this code, and this
# code cannot import theirs. Mirror + lock-test is the deliberate pattern (see
# the BROWSER_ROOTS lock-test above).

SEARCH_MODES: frozenset[str] = frozenset({"substring", "glob", "regex"})

# Depth the MCP push-time resolver walks the browser
# (``hallucinote_mcp.handlers.device._BROWSER_WALK_DEPTH``). An inventory cache
# MUST be walked at least this deep or offline resolution can miss a loadable
# that push would find. Pinned ``>=`` the MCP value by the lock-test
# ``test_browser_walk_depth_matches_mcp_side``.
MIN_WALK_DEPTH: int = 8


def name_matches(
    name: str, pattern: str, mode: str = "substring", case_sensitive: bool = False,
) -> bool:
    """Mirror of ``hallucinote_mcp.handlers.browser._name_matches``.

    The single correctness-critical primitive shared between offline
    authoring and push-time resolution: it decides whether a browser leaf's
    ``name`` matches a preset_query ``pattern``. Pinned to the MCP
    implementation by ``test_name_matches_matches_mcp_side`` — change both
    sides together or the lock-test fails.
    """
    if not case_sensitive:
        name_cmp = name.lower()
        pattern_cmp = pattern.lower()
    else:
        name_cmp = name
        pattern_cmp = pattern
    if mode == "substring":
        return pattern_cmp in name_cmp
    if mode == "glob":
        return fnmatch.fnmatchcase(name_cmp, pattern_cmp)
    if mode == "regex":
        return re.search(pattern_cmp, name_cmp) is not None
    raise ValueError(
        f"unknown search mode {mode!r}; expected one of {sorted(SEARCH_MODES)}"
    )


def resolve_query(query: dict, entries: list[dict]) -> dict:
    """Resolve a canonical ``preset_query`` dict against a flat list of cached
    inventory ``entries``, returning the single matching entry.

    Mirrors the strict semantics of
    ``hallucinote_mcp.handlers.device._resolve_preset_query``: matches on a
    loadable leaf's ``name`` within the query's ``root`` (and optional
    ``path_prefix`` scope), and requires *exactly one* loadable match. 0
    matches or 2+ matches raise ``ValueError`` with a teaching message — the
    same contract the push-time loader enforces, surfaced at authoring time
    instead of push time.

    Each entry is ``{"root", "path", "name", "uri", "is_loadable"}`` where
    ``path`` is the full segment list from the root key to and including the
    leaf name (matching the MCP search-response shape).
    """
    if not isinstance(query, dict):
        raise ValueError("preset_query must be an object")
    pattern = query.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("preset_query.pattern must be a non-empty string")
    root = query.get("root", "instruments")
    mode = query.get("mode", "substring")
    case_sensitive = bool(query.get("case_sensitive", False))
    path_prefix = query.get("path_prefix")
    if mode not in SEARCH_MODES:
        raise ValueError(
            f"preset_query.mode={mode!r}; expected one of {sorted(SEARCH_MODES)}"
        )
    if root not in BROWSER_ROOTS:
        raise ValueError(
            f"preset_query.root={root!r} not in valid roots {sorted(BROWSER_ROOTS)}"
        )

    # Scope path the leaf's path must start with: [root] + path_prefix.
    scope_path = [root]
    if path_prefix is not None:
        if not isinstance(path_prefix, list):
            raise ValueError("preset_query.path_prefix must be a list")
        scope_path = [root] + [str(s) for s in path_prefix]

    in_root = [e for e in entries if e.get("path", [None])[:1] == [root]]
    if not in_root:
        raise ValueError(
            f"preset_query.root={root!r} not present in the inventory cache; "
            "this Live install may not expose that root, or the cache predates "
            "it — refresh the inventory cache."
        )
    if path_prefix:
        in_scope = [
            e for e in in_root
            if e.get("path", [])[: len(scope_path)] == scope_path
        ]
        if not in_scope:
            raise ValueError(
                f"preset_query.path_prefix={path_prefix!r} not found under "
                f"root {root!r} in the inventory cache — verify the prefix or "
                "refresh the cache."
            )
    else:
        in_scope = in_root

    matches = [
        e for e in in_scope
        if e.get("is_loadable")
        and name_matches(str(e.get("name", "")), pattern, mode, case_sensitive)
    ]
    if not matches:
        raise ValueError(
            f"preset_query found no loadable matches for pattern={pattern!r} "
            f"mode={mode!r} root={root!r} path_prefix={path_prefix!r} in the "
            "inventory cache. Tighten the scope, verify the preset is installed, "
            "or refresh the cache (it may predate the install)."
        )
    if len(matches) >= 2:
        details = ", ".join(
            f"{m.get('name')!r} at {'/'.join(m.get('path', []))}"
            for m in matches[:2]
        )
        raise ValueError(
            f"preset_query is ambiguous — matched at least 2: {details}. "
            "Strict mode refuses fuzzy matches. Tighten pattern or add "
            "path_prefix to narrow the scope (the paths above disambiguate)."
        )
    return matches[0]


__all__ = [
    "BROWSER_ROOTS",
    "SEARCH_MODES",
    "MIN_WALK_DEPTH",
    "parse_path_shape",
    "normalize",
    "name_matches",
    "resolve_query",
]
