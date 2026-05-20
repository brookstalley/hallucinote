"""Imperative handlers for ``ableton_browser`` actions.

The browser exposes Live's content library: instruments, effects, drums,
audio loops, plus the installed VST/AU plugins. Live's API: the browser
lives at ``application.browser``, with top-level collections
``instruments``, ``audio_effects``, ``midi_effects``, ``drums``,
``plugins``, ``samples``, ``user_library``, plus a ``packs`` collection.
Each is a ``BrowserItem`` with ``.name`` + ``.children`` + ``.is_folder``
+ ``.is_loadable`` + ``.uri``.

M-5 ships these as actions so the surface is callable. M-6 (Resources)
considers moving the heavy reads (full tree dumps) behind
``ableton://browser/*`` resource URIs to reduce per-call token cost.

The tree walk is bounded: ``tree`` accepts ``depth`` (default 2) to limit
recursion. Without a bound, instrument-library walks can return tens of
thousands of nodes. ``search`` (the agent-facing pattern-match action)
walks deeper by default (8) but stops at a configurable match limit so
the cost is bounded by results, not by library size.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any

from ..dispatcher import LiveContext


_ROOTS = ("instruments", "audio_effects", "midi_effects", "drums", "plugins",
          "samples", "user_library", "packs")


def _resolve_browser(context: LiveContext) -> Any:
    # Application lives on LiveContext.application (the Protocol's symmetric
    # peer to ``song``). Live's Song does NOT expose get_application;
    # routing through the context keeps Live-specific access points off
    # the Song object.
    try:
        app = context.application
    except (AttributeError, RuntimeError):
        app = None
    if app is None:
        raise NotImplementedError(
            "LiveContext.application is unreachable — browser cannot be opened"
        )
    browser = getattr(app, "browser", None)
    if browser is None:
        raise NotImplementedError(
            "application.browser not exposed in this Live version"
        )
    return browser


def _resolve_root(browser: Any, root: str) -> Any:
    if root not in _ROOTS:
        raise ValueError(
            f"root {root!r} not in {list(_ROOTS)}"
        )
    node = getattr(browser, root, None)
    if node is None:
        raise NotImplementedError(
            f"browser.{root} not exposed in this Live version"
        )
    return node


def _walk(node: Any, depth_remaining: int) -> dict[str, Any]:
    """Recursive node serialization to (name, uri, is_loadable, children)."""
    entry: dict[str, Any] = {
        "name": str(getattr(node, "name", "")),
        "uri": getattr(node, "uri", None),
        "is_loadable": bool(getattr(node, "is_loadable", False)),
        "is_folder": bool(getattr(node, "is_folder", False)),
    }
    if depth_remaining > 0:
        children = getattr(node, "children", ()) or ()
        if children:
            entry["children"] = [_walk(c, depth_remaining - 1) for c in children]
    return entry


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


def tree_handler(
    context: LiveContext,
    *,
    root: str = "instruments",
    depth: int = 2,
) -> dict[str, Any]:
    """Read a browser tree from one root, bounded by depth.

    depth=0 returns identity-only (no children); depth=1 returns
    immediate children only; etc. Default depth=2 is enough for most
    "find by category" probes without returning the whole library.
    """
    if depth < 0:
        raise ValueError(f"depth {depth} must be >= 0")
    if depth > 6:
        raise ValueError(
            f"depth {depth} unreasonably deep — Live's library has at most "
            "~5 useful levels; cap at 6 to prevent runaway walks"
        )
    browser = _resolve_browser(context)
    root_node = _resolve_root(browser, root)
    return {
        "root": root,
        "tree": _walk(root_node, depth),
    }


# ---------------------------------------------------------------------------
# at_path
# ---------------------------------------------------------------------------


def at_path_handler(
    context: LiveContext,
    *,
    path: list[str],
) -> dict[str, Any]:
    """Navigate to a specific node by its path: a list of name segments
    rooted at one of the browser roots. The first element MUST be a root
    name; subsequent segments are matched by ``name`` exact-match (Live
    folder names are unique within a parent).

    Returns the node's (name, uri, is_loadable, depth-1 children).
    """
    if not isinstance(path, list) or not path:
        raise ValueError("path must be a non-empty list of name segments")
    root = path[0]
    if root not in _ROOTS:
        raise ValueError(
            f"path[0] (root) {root!r} not in {list(_ROOTS)}"
        )
    browser = _resolve_browser(context)
    node = _resolve_root(browser, root)
    walked: list[str] = [root]
    for segment in path[1:]:
        next_node = None
        for child in getattr(node, "children", ()) or ():
            if str(getattr(child, "name", "")) == segment:
                next_node = child
                break
        if next_node is None:
            available = [
                str(getattr(c, "name", ""))
                for c in (getattr(node, "children", ()) or ())
            ]
            raise ValueError(
                f"path segment {segment!r} not found under "
                f"{' / '.join(walked)}; available: {available}"
            )
        node = next_node
        walked.append(segment)
    return {
        "path": list(path),
        "node": _walk(node, depth_remaining=1),
    }


# ---------------------------------------------------------------------------
# plugins_list
# ---------------------------------------------------------------------------


def plugins_list_handler(context: LiveContext) -> dict[str, Any]:
    """Enumerate installed VST/AU plugins.

    Live exposes the plugin collection as ``browser.plugins`` whose
    children represent each installed plugin (organized by vendor/folder
    on some platforms). We return a flat list of {name, uri,
    is_loadable} at depth 2 (vendor → plugin) to keep payload sizes
    reasonable. Use ``at_path`` for deeper inspection of any one
    plugin's subfolders.
    """
    browser = _resolve_browser(context)
    plugins = _resolve_root(browser, "plugins")
    out: list[dict[str, Any]] = []

    def _flatten(node: Any, depth_left: int) -> None:
        is_loadable = bool(getattr(node, "is_loadable", False))
        if is_loadable:
            out.append({
                "name": str(getattr(node, "name", "")),
                "uri": getattr(node, "uri", None),
            })
            return  # don't recurse into a loadable; its children are presets
        if depth_left <= 0:
            return
        for child in getattr(node, "children", ()) or ():
            _flatten(child, depth_left - 1)

    _flatten(plugins, depth_left=3)
    return {"plugins": out, "count": len(out)}


# ---------------------------------------------------------------------------
# search — agent-facing pattern match over the browser tree
# ---------------------------------------------------------------------------

_SEARCH_MODES = ("substring", "glob", "regex")

# Match limit cap — generous; agents usually want 5-20. Tests against scale
# (large library walks past this number stop early).
_SEARCH_MAX_LIMIT = 200

# Depth cap is higher than `tree`'s 6 because the agent picks a root and
# pattern; if neither narrows the space, we still want to surface a useful
# result rather than miss leaves at depth 7 (some pack libraries nest that
# deep). 12 is well above what any installed library has been observed at.
_SEARCH_MAX_DEPTH = 12


class _SearchTruncated(Exception):
    """Raised internally when the match limit is reached, so the walk
    short-circuits cleanly without making every recursion branch carry an
    'enough' flag. The handler catches it at the top."""


def _name_matches(name: str, pattern: str, mode: str, case_sensitive: bool) -> bool:
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
        # re.IGNORECASE is implicit when case_sensitive=False because we
        # already lowercased both sides.
        return re.search(pattern_cmp, name_cmp) is not None
    raise ValueError(f"unknown search mode {mode!r}; expected one of {_SEARCH_MODES}")


def _navigate_path_prefix(node: Any, segments: list[str]) -> Any:
    """Walk a path prefix under an already-resolved root, returning the
    deepest reached node. Raises ValueError if a segment is missing — the
    error names what IS available so the agent can re-narrow."""
    walked: list[str] = []
    for segment in segments:
        next_node = None
        for child in getattr(node, "children", ()) or ():
            if str(getattr(child, "name", "")) == segment:
                next_node = child
                break
        if next_node is None:
            available = [
                str(getattr(c, "name", ""))
                for c in (getattr(node, "children", ()) or ())
            ]
            raise ValueError(
                f"path_prefix segment {segment!r} not found "
                f"under {' / '.join(walked) or '<root>'}; available: {available}"
            )
        node = next_node
        walked.append(segment)
    return node


def _search_walk(
    node: Any,
    *,
    pattern: str,
    mode: str,
    case_sensitive: bool,
    loadable_only: bool,
    path: list[str],
    depth_left: int,
    matches: list[dict[str, Any]],
    limit: int,
    depth_exhausted: list[bool],
) -> None:
    """Recursive search walk. Appends matches in-place; raises
    :class:`_SearchTruncated` once limit is hit so the outer call short-circuits.

    ``path`` is the full path TO AND INCLUDING ``node`` (caller supplies the
    leading root key). Children's paths are constructed as ``path +
    [child.name]``. ``depth_exhausted`` is a single-element list used as a
    mutable flag so any branch that hits depth_left==0 with un-walked children
    surfaces the warning."""
    name = str(getattr(node, "name", ""))
    is_loadable = bool(getattr(node, "is_loadable", False))
    uri = getattr(node, "uri", None)
    children = getattr(node, "children", ()) or ()

    if _name_matches(name, pattern, mode, case_sensitive):
        if (not loadable_only) or is_loadable:
            matches.append({
                "name": name,
                "uri": uri,
                "path": list(path),
                "is_loadable": is_loadable,
            })
            if len(matches) >= limit:
                raise _SearchTruncated

    if depth_left <= 0:
        if children:
            depth_exhausted[0] = True
        return

    for child in children:
        child_name = str(getattr(child, "name", ""))
        _search_walk(
            child,
            pattern=pattern, mode=mode, case_sensitive=case_sensitive,
            loadable_only=loadable_only,
            path=path + [child_name], depth_left=depth_left - 1,
            matches=matches, limit=limit, depth_exhausted=depth_exhausted,
        )


def search_handler(
    context: LiveContext,
    *,
    pattern: str,
    root: str = "instruments",
    path_prefix: list[str] | None = None,
    mode: str = "substring",
    case_sensitive: bool = False,
    loadable_only: bool = True,
    depth: int = 8,
    limit: int = 20,
) -> dict[str, Any]:
    """Walk a browser sub-tree, return nodes whose name matches ``pattern``.

    The categorical tree IS the typing for browser items: a node under
    ``instruments/Operator/Bass/...`` is an Operator preset in the Bass
    category. So ``search`` is a query surface that lets an agent NOT
    have to know exact names — it provides a pattern + an optional
    category scope (root + path_prefix) and gets back candidate URIs
    with their paths for disambiguation.

    Modes:

    * ``substring`` (default, case-insensitive) — ``'909'`` matches
      ``'Kit-Core 909'`` and ``'Live 909'``.
    * ``glob`` — fnmatch syntax: ``'*909*'`` ``'Bass-?'`` ``'[Pp]ad*'``.
    * ``regex`` — full :mod:`re` syntax.

    ``loadable_only=True`` (default) filters out folders, returning only
    nodes that ``browser.load_item(node)`` can instantiate.

    The walk is bounded by ``depth`` (max 12) AND by ``limit`` (max 200).
    Whichever bound is hit first wins; the response carries
    ``truncated`` / ``depth_exhausted`` flags so the agent knows whether
    to widen the scope or narrow the pattern.

    The agent doesn't need to know exact names. It picks the closest
    category (root + path_prefix) and a loose pattern; the response carries
    full paths so it can pick the right URI.
    """
    if not isinstance(pattern, str) or pattern == "":
        raise ValueError("pattern must be a non-empty string")
    if mode not in _SEARCH_MODES:
        raise ValueError(
            f"mode {mode!r} not in {list(_SEARCH_MODES)}"
        )
    if depth < 0 or depth > _SEARCH_MAX_DEPTH:
        raise ValueError(
            f"depth {depth} out of bounds [0, {_SEARCH_MAX_DEPTH}]"
        )
    if limit < 1 or limit > _SEARCH_MAX_LIMIT:
        raise ValueError(
            f"limit {limit} out of bounds [1, {_SEARCH_MAX_LIMIT}]"
        )
    if mode == "regex":
        # Validate the pattern compiles before walking — surfaces the regex
        # error at the call boundary rather than mid-walk.
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern {pattern!r}: {exc}") from exc

    browser = _resolve_browser(context)
    root_node = _resolve_root(browser, root)

    if path_prefix:
        if not isinstance(path_prefix, list):
            raise ValueError("path_prefix must be a list of name segments")
        scope_node = _navigate_path_prefix(root_node, [str(s) for s in path_prefix])
        scope_path = [root] + list(path_prefix)
    else:
        scope_node = root_node
        scope_path = [root]

    # `path` passed to the walk is the full path TO AND INCLUDING the
    # scope node — i.e. `[root]` for a scope-less search, or
    # `[root, *path_prefix]` when path_prefix narrows the scope. The walk's
    # match-record uses `path` verbatim, and recurses into children with
    # `path + [child.name]`.
    matches: list[dict[str, Any]] = []
    depth_exhausted: list[bool] = [False]
    truncated = False
    try:
        _search_walk(
            scope_node,
            pattern=pattern, mode=mode, case_sensitive=case_sensitive,
            loadable_only=loadable_only,
            path=scope_path, depth_left=depth,
            matches=matches, limit=limit, depth_exhausted=depth_exhausted,
        )
    except _SearchTruncated:
        truncated = True

    return {
        "matches": matches,
        "count": len(matches),
        "truncated": truncated,
        "depth_exhausted": depth_exhausted[0],
    }


__all__ = [
    "tree_handler",
    "at_path_handler",
    "plugins_list_handler",
    "search_handler",
]
