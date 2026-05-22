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


__all__ = ["BROWSER_ROOTS", "parse_path_shape", "normalize"]
