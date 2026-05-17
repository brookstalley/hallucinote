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
thousands of nodes.
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext


_ROOTS = ("instruments", "audio_effects", "midi_effects", "drums", "plugins",
          "samples", "user_library", "packs")


def _resolve_browser(context: LiveContext) -> Any:
    song = context.song
    app = song.get_application() if hasattr(song, "get_application") else None
    if app is None:
        raise NotImplementedError(
            "song.get_application() not exposed in this Live version — "
            "browser is unreachable"
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


__all__ = [
    "tree_handler",
    "at_path_handler",
    "plugins_list_handler",
]
