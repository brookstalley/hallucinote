"""Imperative handlers for ``ableton_device`` actions.

Devices live on either a track or a return track. The Live Object Model
exposes both via the same per-chain ``devices`` collection — the only
difference is the navigation root. Handlers address devices via exactly
one of ``track_index`` / ``return_index`` (validated by
``_resolve_parent``) so the agent's mental model stays close to Live's UI
(devices belong to tracks or returns) without forcing a separate
``parent_kind`` param.

set_parameter handles both continuous and enum values via ``value_type``.
Live's DeviceParameter has ``value`` (always a float — for enum params it
is an index into ``value_items``) plus ``value_items`` (tuple of strings)
plus ``str_to_value`` (parses a display string). For the enum path the
handler maps wire ``value`` (string) to an index via ``value_items`` and
writes that. For continuous the handler validates 0.0–1.0 range and
writes via ``value``.

Nested rack chains are deliberately out of scope for M-4 — the parent_chain
walk stops at the top-level chain. Recursing into instrument-rack or
drum-rack chains is tracked in the backlog (capture-side device chain
extension).
"""
from __future__ import annotations

from typing import Any

from .. import device_names
from ..dispatcher import LiveContext


_PARENT_KINDS = ("track", "return")


def _resolve_parent(
    context: LiveContext,
    *,
    track_index: int | None,
    return_index: int | None,
) -> tuple[Any, str, int]:
    """Return (parent_object, kind, 1-based-index). Raises if neither or both."""
    if track_index is None and return_index is None:
        raise ValueError(
            "must specify exactly one of track_index or return_index "
            "(devices live on a track or a return)"
        )
    if track_index is not None and return_index is not None:
        raise ValueError(
            "specify exactly one of track_index or return_index, not both"
        )
    song = context.song
    if track_index is not None:
        if track_index < 1 or track_index > len(song.tracks):
            raise IndexError(
                f"track_index {track_index} out of range "
                f"[1, {len(song.tracks)}]"
            )
        return song.tracks[track_index - 1], "track", track_index
    assert return_index is not None
    if return_index < 1 or return_index > len(song.return_tracks):
        raise IndexError(
            f"return_index {return_index} out of range "
            f"[1, {len(song.return_tracks)}]"
        )
    return song.return_tracks[return_index - 1], "return", return_index


def _resolve_device(parent: Any, device_index: int) -> Any:
    devices = parent.devices
    if device_index < 1 or device_index > len(devices):
        raise IndexError(
            f"device_index {device_index} out of range [1, {len(devices)}]"
        )
    return devices[device_index - 1]


def _parent_address(kind: str, index: int) -> dict[str, Any]:
    """Build the (kind-specific) key for return values."""
    return {f"{kind}_index": index}


# ---------------------------------------------------------------------------
# list / info / get_parameters
# ---------------------------------------------------------------------------


def list_handler(
    context: LiveContext,
    *,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Return the top-level device chain on a track or return.

    Identity only (name, class_name, class_display_name, position).
    Per-device detail (parameters, routing, etc.) is each device's
    ``info`` action's job.

    Arc 4 / D4: ``class_display_name`` is Live's
    ``device.class_display_name`` — the browser display name the
    loader's kind-as-given walk matches against. For default-loaded
    devices it equals ``name``; for preset-loaded or user-renamed
    devices it diverges (preserves the underlying device class). The
    pull-side ingest stores this as ``devices.kind`` and ``class_name``
    as ``devices.class_name``; the loader's resolution no longer needs
    a static translation table.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    devices_out: list[dict[str, Any]] = []
    for i, dev in enumerate(parent.devices, start=1):
        devices_out.append({
            "device_index": i,
            "name": getattr(dev, "name", ""),
            "class_name": getattr(dev, "class_name", ""),
            "class_display_name": getattr(dev, "class_display_name", None),
            "is_active": bool(getattr(dev, "is_active", True)),
        })
    result: dict[str, Any] = {"parent_kind": kind, "devices": devices_out}
    result.update(_parent_address(kind, idx))
    return result


def info_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Identity + activation + parameter count for one device."""
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    params = getattr(dev, "parameters", ())
    result: dict[str, Any] = {
        "device_index": device_index,
        "name": getattr(dev, "name", ""),
        "class_name": getattr(dev, "class_name", ""),
        # Arc 4 / D4: browser display name (drives kind-as-given resolution
        # on the loader side; pull writes this into devices.kind).
        "class_display_name": getattr(dev, "class_display_name", None),
        "is_active": bool(getattr(dev, "is_active", True)),
        "parameter_count": len(params),
        "can_have_chains": bool(getattr(dev, "can_have_chains", False)),
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


def get_parameters_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
    detail: str = "summary",
) -> dict[str, Any]:
    """Return device parameters with current values.

    ``detail='summary'`` returns name + value + value_display (cheap).
    ``detail='full'`` adds min/max + is_enum + value_items (more expensive
    on devices with many enum params).
    """
    if detail not in ("summary", "full"):
        raise ValueError(
            f"detail must be 'summary' or 'full', got {detail!r}"
        )
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    params_out: list[dict[str, Any]] = []
    for p in getattr(dev, "parameters", ()):
        entry: dict[str, Any] = {
            "name": p.name,
            "value": float(p.value),
            "value_display": str(getattr(p, "str_for_value", lambda v: "")(p.value))
                if hasattr(p, "str_for_value") else "",
        }
        if detail == "full":
            entry["min"] = float(getattr(p, "min", 0.0))
            entry["max"] = float(getattr(p, "max", 1.0))
            # Live raises ``RuntimeError: Only quantized parameters have
            # value items`` on continuous-parameter ``value_items`` access.
            # Guard via ``is_quantized`` before reading.
            if bool(getattr(p, "is_quantized", False)):
                items = tuple(getattr(p, "value_items", ()) or ())
                entry["is_enum"] = bool(items)
                if items:
                    entry["value_items"] = list(items)
            else:
                entry["is_enum"] = False
        params_out.append(entry)
    result: dict[str, Any] = {
        "device_index": device_index,
        "parent_kind": kind,
        "parameters": params_out,
    }
    result.update(_parent_address(kind, idx))
    return result


# ---------------------------------------------------------------------------
# load / delete
# ---------------------------------------------------------------------------


_BROWSER_LOAD_ROOTS: tuple[str, ...] = (
    "instruments",
    "audio_effects",
    "midi_effects",
    "drums",
)

_BROWSER_URI_ROOTS: tuple[str, ...] = _BROWSER_LOAD_ROOTS + (
    "plugins",
    "samples",
    "user_library",
    "packs",
)

_BROWSER_WALK_DEPTH = 8


def _walk_for_uri(node: Any, target_uri: str, depth_left: int) -> Any:
    # Gate on is_loadable so an empty / folder URI doesn't resolve to a
    # non-loadable node and produce a misleading "did not append" error
    # later. browser.load_item requires a loadable BrowserItem.
    if (
        bool(getattr(node, "is_loadable", False))
        and getattr(node, "uri", None) == target_uri
    ):
        return node
    if depth_left <= 0:
        return None
    for child in getattr(node, "children", ()) or ():
        match = _walk_for_uri(child, target_uri, depth_left - 1)
        if match is not None:
            return match
    return None


def _walk_for_name(node: Any, name: str, depth_left: int) -> Any:
    if (
        bool(getattr(node, "is_loadable", False))
        and str(getattr(node, "name", "")) == name
    ):
        return node
    if depth_left <= 0:
        return None
    for child in getattr(node, "children", ()) or ():
        match = _walk_for_name(child, name, depth_left - 1)
        if match is not None:
            return match
    return None


def _resolve_preset_query(browser: Any, query: dict[str, Any]) -> Any:
    """Resolve a ``preset_query`` dict to a single loadable BrowserItem.

    Compose-time portable preset selection: snapshot stores a query
    (root + pattern + optional mode/path_prefix) instead of a per-machine
    ``preset_uri`` (FileIds differ across machines). At push time the
    handler walks the browser via the same primitive used by
    ``ableton_browser(action='search')`` and picks the single matching
    loadable.

    Strict — refuses ambiguity. Exactly one match is required. 0 matches
    or 2+ matches raise ValueError with a teaching error so the composer
    knows to tighten or loosen the query. The ambiguity error includes
    each match's full path so the agent can disambiguate by adding
    ``path_prefix``.
    """
    # Local imports avoid a module-load cycle: device.py is imported by
    # actions/device.py at registration time; browser handler imports
    # the same dispatcher base. Importing at call time keeps the load
    # graph linear.
    from .browser import _name_matches, _navigate_path_prefix
    if not isinstance(query, dict):
        raise ValueError("preset_query must be an object")
    pattern = query.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("preset_query.pattern must be a non-empty string")
    root = query.get("root", "instruments")
    mode = query.get("mode", "substring")
    case_sensitive = bool(query.get("case_sensitive", False))
    path_prefix = query.get("path_prefix")
    if mode not in {"substring", "glob", "regex"}:
        raise ValueError(
            f"preset_query.mode={mode!r}; expected 'substring', 'glob', or 'regex'"
        )

    root_node = getattr(browser, root, None)
    if root_node is None:
        raise ValueError(
            f"preset_query.root={root!r} not in browser; this Live version "
            f"may not expose that root"
        )
    scope_node = root_node
    scope_path = [root]
    if path_prefix:
        if not isinstance(path_prefix, list):
            raise ValueError("preset_query.path_prefix must be a list")
        try:
            scope_node = _navigate_path_prefix(
                root_node, [str(s) for s in path_prefix],
            )
        except ValueError as exc:
            # Re-raise with the preset_query prefix so the agent knows
            # the failure originated from the preset_query path.
            raise ValueError(f"preset_query.{exc}") from None
        scope_path = [root] + [str(s) for s in path_prefix]

    # Cap matches at 2 — we only need to know "exactly 1" vs "0 or 2+".
    # Inline the walk here (rather than reusing browser._search_walk) so
    # we keep references to the BrowserItem objects themselves, not just
    # their dict-serialized form — browser.load_item needs the live item.
    matches: list[dict[str, Any]] = []
    found_items: list[Any] = []

    def _walk(node: Any, path: list[str], depth_left: int) -> bool:
        name = str(getattr(node, "name", ""))
        is_loadable = bool(getattr(node, "is_loadable", False))
        if is_loadable and _name_matches(name, pattern, mode, case_sensitive):
            found_items.append(node)
            matches.append({
                "name": name,
                "uri": getattr(node, "uri", None),
                "path": list(path),
            })
            if len(found_items) >= 2:
                return True  # done — we know it's ambiguous
        if depth_left <= 0:
            return False
        for child in getattr(node, "children", ()) or ():
            child_name = str(getattr(child, "name", ""))
            if _walk(child, path + [child_name], depth_left - 1):
                return True
        return False

    _walk(scope_node, scope_path, _BROWSER_WALK_DEPTH)

    if not found_items:
        raise ValueError(
            f"preset_query found no loadable matches for "
            f"pattern={pattern!r} mode={mode!r} root={root!r} "
            f"path_prefix={path_prefix!r}. Tighten the scope or "
            "verify the preset is installed via "
            "ableton_browser(action='search', ...)."
        )
    if len(found_items) >= 2:
        details = ", ".join(
            f"{m['name']!r} at {'/'.join(m['path'])}"
            for m in matches[:2]
        )
        raise ValueError(
            f"preset_query is ambiguous — matched at least 2: {details}. "
            "Strict-mode loader refuses fuzzy matches. Tighten pattern "
            "or add path_prefix to narrow the scope (the paths above "
            "are the disambiguating segments)."
        )
    return found_items[0]


def _roots_for_kind(kind: str) -> tuple[str, ...]:
    """Pick the browser roots to walk for a ``kind``.

    Rack display names ("Drum Rack", "Instrument Rack", "Audio Effect
    Rack", "MIDI Effect Rack") restrict the walk to their canonical
    category root — a user-saved preset named "Drum Rack" in the
    instruments root must not shadow the canonical empty Drum Rack
    node in the drums root (W7-0 finding, preserved post-D4).
    """
    rack_root = device_names.browser_root_for_rack_kind(kind)
    if rack_root is not None:
        return (rack_root,)
    return _BROWSER_LOAD_ROOTS


def _format_kind_failure_criteria(kind: str) -> str:
    """Build the failure-criteria string for an unresolvable ``kind``.

    Arc 4 / D4: the loader is now kind-as-given against the browser
    (no static translation table — that data lives on Live's own
    ``device.class_display_name`` attribute, captured by pull). So a
    failure means the kind doesn't match any browser node directly.
    The rack-root callout still applies (W7-0 protection).
    """
    base = f"kind={kind!r}"
    rack_root = device_names.browser_root_for_rack_kind(kind)
    if rack_root is not None:
        base += (
            f"; rack kinds are searched only in the '{rack_root}' browser "
            "root (W7-0 cross-category disambiguation). For an empty "
            "Instrument Rack, group devices in Live (Cmd+G) or pass "
            "preset_uri to a saved .adg"
        )
    return base


def _find_browser_item(
    browser: Any, *, kind: str, preset_uri: str | None
) -> Any:
    """Resolve a BrowserItem to hand to ``browser.load_item``.

    With ``preset_uri``: walk every root (including plugins / packs / user
    library) looking for an exact ``uri`` match. With ``kind`` only:
    walk the built-in roots for a loadable node whose display name
    equals ``kind`` (kind-as-given match against Live's browser tree).
    Rack display names restrict the walk to the canonical category
    root via :func:`_roots_for_kind`.

    Arc 4 / D4: ``kind`` is the post-D4 browser display name (from
    ``devices.kind`` populated by pull from ``class_display_name``).
    No static class-name → display translation step — the data flows
    through Live's own attribute now.

    Agents loading third-party plugins or specific presets should pass
    ``preset_uri`` — captured via ``ableton_browser(action='at_path',
    ...)``. For compose-time cross-machine portable selection use
    ``preset_query`` — see :func:`_resolve_preset_query`.
    """
    if preset_uri is not None:
        for root_name in _BROWSER_URI_ROOTS:
            root_node = getattr(browser, root_name, None)
            if root_node is None:
                continue
            match = _walk_for_uri(root_node, preset_uri, _BROWSER_WALK_DEPTH)
            if match is not None:
                return match
        return None

    for root_name in _roots_for_kind(kind):
        root_node = getattr(browser, root_name, None)
        if root_node is None:
            continue
        match = _walk_for_name(root_node, kind, _BROWSER_WALK_DEPTH)
        if match is not None:
            return match
    return None


def _refresh_parent(
    context: LiveContext, *, parent_kind: str, parent_idx: int
) -> Any:
    """Re-read the parent track after a Live mutation.

    Live 12.x re-wraps API objects on every property access (B-1). The
    parent reference captured before ``browser.load_item`` may point to
    a stale wrapper whose ``devices`` collection doesn't reflect the new
    chain. Re-resolving from ``song`` returns the fresh wrapper.
    """
    if parent_kind == "track":
        return context.song.tracks[parent_idx - 1]
    return context.song.return_tracks[parent_idx - 1]


def load_handler(
    context: LiveContext,
    *,
    kind: str,
    preset_uri: str | None = None,
    preset_query: dict[str, Any] | None = None,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Load a device onto a track or return chain.

    ``kind`` is the device's BROWSER DISPLAY NAME (e.g. ``'Compressor'``,
    ``'Operator'``, ``'Drum Rack'``, ``'Phaser-Flanger'``) — what shows up
    in Live's browser tree and what the loader matches against directly.
    Arc 4 / D4: Live's internal class names (``'Compressor2'``,
    ``'PhaserNew'``, ``'DrumGroupDevice'``) no longer resolve; pull
    writes the display name into ``devices.kind`` from Live's
    ``device.class_display_name`` attribute.

    Three selector paths, in precedence order:

    1. ``preset_query`` (most portable): a dict ``{root, pattern, mode?,
       path_prefix?, case_sensitive?}`` resolved at load time via the
       same primitive as ``ableton_browser(action='search')``. Strict —
       must match exactly one loadable. The composer expresses
       "a 909 kit" or "the Late Nite drum rack"; this machine's
       installed library decides the actual URI. The cross-machine
       portability path (no per-machine FileId in the snapshot).
    2. ``preset_uri``: the canonical Live browser URI captured via
       ``ableton_browser(action='at_path', ...)``. Per-machine
       (FileIds differ across machines) but unambiguous on this one.
    3. ``kind`` only: walk the built-in roots for the first loadable
       node whose display name matches. Adequate for built-in classes.

    ``preset_query`` and ``preset_uri`` are mutually exclusive — pass one
    or the other (or neither, for kind-only).

    Selects the destination via ``song.view.selected_track = parent`` and
    calls ``application.browser.load_item(item)``. The new device appears
    at the tail of the destination's top-level device chain; Live 12.4
    exposes no public re-ordering API, so the position is fixed.
    """
    parent, parent_kind, parent_idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be a non-empty Live device class name")
    if preset_query is not None and preset_uri is not None:
        raise ValueError(
            "preset_query and preset_uri are mutually exclusive — pass "
            "one (preset_query for portable compose-time selection, "
            "preset_uri for an unambiguous per-machine URI)"
        )

    application = getattr(context, "application", None)
    if application is None:
        raise NotImplementedError(
            "LiveContext.application is unreachable — browser cannot be "
            "opened for device load"
        )
    browser = getattr(application, "browser", None)
    if browser is None:
        raise NotImplementedError(
            "application.browser not exposed in this Live version"
        )

    if preset_query is not None:
        item = _resolve_preset_query(browser, preset_query)
    else:
        item = _find_browser_item(browser, kind=kind, preset_uri=preset_uri)
    if item is None:
        if preset_uri is not None:
            criteria = f"preset_uri={preset_uri!r}"
        else:
            criteria = _format_kind_failure_criteria(kind)
        raise ValueError(
            f"no loadable browser item found for {criteria}; verify via "
            "ableton_browser(action='tree', ...) or pass preset_uri from "
            "ableton_browser(action='at_path', ...)"
        )

    view = getattr(context.song, "view", None)
    if view is None:
        raise NotImplementedError(
            "song.view not exposed — cannot select destination track for "
            "browser.load_item"
        )

    chain_before = len(parent.devices)
    view.selected_track = parent
    browser.load_item(item)

    # Re-resolve the parent — Live re-wraps Track objects on every property
    # access, and `browser.load_item` may invalidate the captured wrapper.
    fresh_parent = _refresh_parent(
        context, parent_kind=parent_kind, parent_idx=parent_idx
    )
    chain_after = list(fresh_parent.devices)
    if len(chain_after) <= chain_before:
        # A2-resid: surface what's actually on the parent so the caller can
        # diagnose without a separate ableton_device(action='list') probe.
        # The two empirical no-append causes are (a) browser silently no-ops
        # because a matching device is already at this position (the
        # punk-fate `--reset`-then-repush repro) and (b) the item isn't
        # actually loadable on this parent kind (instrument on a return).
        # The pre-A2-resid error only named (b), which misleads on (a) —
        # by far the more common case in iteration loops. Listing the
        # existing chain disambiguates: if a same-class device already sits
        # at the expected position, that's (a).
        existing = [
            f"{i + 1}:{getattr(d, 'class_name', '?')}"
            for i, d in enumerate(chain_after)
        ]
        existing_str = ", ".join(existing) if existing else "(empty)"
        suffix = (
            "; the item may not be loadable on this parent (instrument on a return)"
            if parent_kind == "return"
            else ""
        )
        raise RuntimeError(
            f"load: Live did not append a device on {parent_kind} "
            f"{parent_idx} after browser.load_item. Existing chain: "
            f"[{existing_str}]. Most common cause: a device with matching "
            f"class is already present at the expected position (Live "
            f"silently no-ops the load){suffix}."
        )
    new_device = chain_after[-1]
    new_index = len(chain_after)
    # Arc 7 / P5: surface the device's resolved class display name so
    # the caller can detect a kind / preset_uri mismatch without a
    # follow-up ableton_device(action='list'). Prefer class_display_name
    # (the Arc 4 / D4 native attribute the rest of the pipeline uses)
    # and fall back to class_name when the wrapper is too old to expose
    # it. Empty string when neither is present rather than None so the
    # wire shape stays string-typed.
    loaded_class_name = (
        getattr(new_device, "class_display_name", None)
        or getattr(new_device, "class_name", None)
        or ""
    )
    result: dict[str, Any] = {
        "device_index": new_index,
        "kind": kind,
        "loaded_class_name": loaded_class_name,
        "name": getattr(new_device, "name", ""),
        "parent_kind": parent_kind,
    }
    result.update(_parent_address(parent_kind, parent_idx))
    if preset_uri is not None:
        result["preset_uri"] = preset_uri
    return result


def delete_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Remove a device from a track or return chain."""
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    _ = _resolve_device(parent, device_index)  # validates range
    delete_fn = getattr(parent, "delete_device", None)
    if delete_fn is None:
        raise NotImplementedError(
            f"{kind} does not expose delete_device — older Live build "
            "or unsupported track type"
        )
    delete_fn(device_index - 1)  # Live's API is 0-based
    result: dict[str, Any] = {
        "deleted_device_index": device_index,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


# ---------------------------------------------------------------------------
# enable / disable / set_parameter
# ---------------------------------------------------------------------------


def _set_active(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None,
    return_index: int | None,
    is_active: bool,
) -> dict[str, Any]:
    """Toggle a device's active/bypass state.

    Live 12.4 exposes ``device.is_active`` as READ-ONLY on at least
    Compressor / CompressorDevice — direct attribute writes raise
    ``AttributeError: property of 'CompressorDevice' object has no
    setter``. The writable surface is the "Device On" parameter (always
    ``device.parameters[0]`` by Live convention). Write to that
    parameter's ``value``; fall back to ``is_active`` only if no
    Device-On parameter is found (defensive — should never happen for a
    real Live device).
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    target_value = 1.0 if is_active else 0.0

    # Prefer the Device-On parameter (the writable surface on Live 12.4).
    params = getattr(dev, "parameters", ())
    device_on = None
    if params:
        first = params[0]
        if getattr(first, "name", "") == "Device On":
            device_on = first
    if device_on is not None:
        device_on.value = target_value
        return {
            "device_index": device_index,
            "is_active": is_active,
            "parent_kind": kind,
            **_parent_address(kind, idx),
        }

    # Fallback: direct attribute write. On Live 12.4 CompressorDevice this
    # raises; surface a teaching error rather than the raw AttributeError.
    try:
        dev.is_active = is_active
    except AttributeError as exc:
        raise NotImplementedError(
            f"device(action='{'enable' if is_active else 'disable'}'): the "
            f"device at index {device_index} exposes neither a 'Device On' "
            f"parameter nor a writable 'is_active' attribute "
            f"(class={type(dev).__name__}). Original error: {exc}. "
            "Live API surface for this device class doesn't support "
            "enable/disable from the Remote Script."
        ) from exc
    return {
        "device_index": device_index,
        "is_active": is_active,
        "parent_kind": kind,
        **_parent_address(kind, idx),
    }


def enable_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    return _set_active(
        context,
        device_index=device_index,
        track_index=track_index,
        return_index=return_index,
        is_active=True,
    )


def disable_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    return _set_active(
        context,
        device_index=device_index,
        track_index=track_index,
        return_index=return_index,
        is_active=False,
    )


_VALUE_TYPES = ("continuous", "enum")


def set_parameter_handler(
    context: LiveContext,
    *,
    device_index: int,
    parameter_name: str,
    value: Any,
    value_type: str = "continuous",
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Write one device parameter.

    ``value_type='continuous'`` (default): ``value`` must be a float in
    [param.min, param.max]. The handler writes via Live's ``parameter.value``.

    ``value_type='enum'``: ``value`` must be a string in
    ``parameter.value_items``. The handler resolves it to the index of that
    item in ``value_items`` and writes the index via ``parameter.value``
    (which is how Live represents enum state internally).

    Resolves the legacy fork's gap #17b workaround — the new path doesn't
    depend on the broken ``set_device_parameter`` fork tool.
    """
    if value_type not in _VALUE_TYPES:
        raise ValueError(
            f"value_type must be one of {list(_VALUE_TYPES)}, got {value_type!r}"
        )
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    target_param = None
    for p in getattr(dev, "parameters", ()):
        if p.name == parameter_name:
            target_param = p
            break
    if target_param is None:
        available = [p.name for p in getattr(dev, "parameters", ())]
        raise ValueError(
            f"parameter {parameter_name!r} not found on device "
            f"{device_index}; available: {available}"
        )

    if value_type == "enum":
        # Live raises RuntimeError on continuous-parameter value_items access
        # (Wave-2 W2-9). Guard via is_quantized — when False, the parameter
        # has no enum items by definition.
        if not bool(getattr(target_param, "is_quantized", False)):
            raise ValueError(
                f"parameter {parameter_name!r} is not an enum parameter "
                f"(is_quantized=False); use value_type='continuous'"
            )
        items = tuple(getattr(target_param, "value_items", ()) or ())
        if not items:
            raise ValueError(
                f"parameter {parameter_name!r} is not an enum parameter "
                f"(no value_items); use value_type='continuous'"
            )
        if not isinstance(value, str):
            raise ValueError(
                f"value_type='enum' requires value as a string, got "
                f"{type(value).__name__}"
            )
        if value not in items:
            raise ValueError(
                f"enum value {value!r} not in value_items for parameter "
                f"{parameter_name!r}: {list(items)}"
            )
        new_value: float = float(items.index(value))
        target_param.value = new_value
    else:
        try:
            coerced = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"value_type='continuous' requires a numeric value, got "
                f"{value!r}"
            ) from exc
        p_min = float(getattr(target_param, "min", 0.0))
        p_max = float(getattr(target_param, "max", 1.0))
        if not (p_min <= coerced <= p_max):
            raise ValueError(
                f"value {coerced} out of range [{p_min}, {p_max}] for "
                f"parameter {parameter_name!r}"
            )
        target_param.value = coerced

    result: dict[str, Any] = {
        "device_index": device_index,
        "parameter_name": parameter_name,
        "value": float(target_param.value),
        "value_type": value_type,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


# ---------------------------------------------------------------------------
# Sidechain / routing / preset / pad_info
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Capability-probing primitives (W6-E-2; project memory:
# feedback_third_party_devices_require_capability_probing)
#
# The previous set_sidechain handler hard-coded a Compressor/Compressor2
# class whitelist + a fictional `sidechain_active` attribute that doesn't
# exist on real Live devices. Both broke immediately against the
# third-party VST/AU ecosystem, where naming and routing capabilities
# vary per plugin author. The primitives below replace that pattern with
# probe + adapt: each action discovers what the device actually exposes
# and acts uniformly when possible, raises a structured teaching error
# when not. See W6-E-1 findings in .prawduct/.session-reflected for the
# empirical basis (real-Live probe of Compressor / Compressor2 / Glue /
# Gate / Multiband Dynamics, 2026-05-19).
# ---------------------------------------------------------------------------


# Substring patterns used to recognize sidechain-related parameters across
# native devices AND third-party plugins. Live natives use 'S/C *'; common
# third-party variants include 'External Side*', 'SC *', 'Side *',
# 'Sidechain *'. Match case-insensitively; the LLM picks the right name
# from the returned candidates when there's ambiguity.
_SIDECHAIN_NAME_HINTS = ("s/c", "sidechain", "side ", "external side", "ext side")


def _looks_like_sidechain_param(name: str) -> bool:
    lower = (name or "").lower()
    return any(hint in lower for hint in _SIDECHAIN_NAME_HINTS)


def _find_routing_by_display_name(
    available: Any, display_name: str
) -> Any | None:
    """Walk a Live RoutingTypeVector / RoutingChannelVector finding
    the first entry whose ``display_name`` matches exactly.

    Returns None when not found — caller composes a teaching error
    with the available names listed.
    """
    if available is None:
        return None
    for entry in available:
        if getattr(entry, "display_name", "") == display_name:
            return entry
    return None


def _enumerate_available(available: Any) -> list[str]:
    """Walk a routing vector and collect display_names for teaching errors."""
    if available is None:
        return []
    out: list[str] = []
    for entry in available:
        dn = getattr(entry, "display_name", None)
        if dn is not None:
            out.append(dn)
    return out


def set_input_routing_handler(
    context: LiveContext,
    *,
    device_index: int,
    type_display_name: str,
    track_index: int | None = None,
    return_index: int | None = None,
    channel_display_name: str | None = None,
) -> dict[str, Any]:
    """Set a device's input routing (sidechain source) by display_name.

    Uniform mechanism — works for ANY device that exposes Live's modern
    ``input_routing_*`` API on the Device class. That includes Compressor,
    Compressor2, and third-party VST3/AU plugins that declare sidechain
    inputs in their plugin manifest. Devices that don't expose the API
    (Glue Compressor, Gate, Multiband Dynamics, older plugins without
    sidechain input declarations) raise a structured teaching error
    pointing at the workarounds.

    ``type_display_name`` is the routing source's display name as it
    appears in Live's UI ("1-Drums", "A-Reverb", "Main", "No Input", etc.).
    Pass "No Input" to disable the sidechain source without removing the
    device. ``channel_display_name`` optionally sets the sub-routing
    (Pre FX / Post FX / Post Mixer); omit to leave the channel unchanged.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    available_types = getattr(dev, "available_input_routing_types", None)
    if available_types is None:
        class_name = getattr(dev, "class_name", "<unknown>")
        raise NotImplementedError(
            f"device {class_name!r} does not expose input_routing_* on the "
            "Device class — Live restricts source routing to UI "
            "configuration for this device family (Glue Compressor, Gate, "
            "Multiband Dynamics, and older plugins without declared "
            "sidechain inputs are the common cases). Workarounds: "
            "(a) set the sidechain source manually in Live's device view; "
            "(b) configure via the plugin's own parameters if it exposes "
            "internal sidechain routing (call ableton_device(action="
            "'get_parameters') to discover names)."
        )

    matched_type = _find_routing_by_display_name(
        available_types, type_display_name
    )
    if matched_type is None:
        raise ValueError(
            f"input routing type {type_display_name!r} not in available "
            f"types {_enumerate_available(available_types)!r}"
        )
    dev.input_routing_type = matched_type

    matched_channel = None
    if channel_display_name is not None:
        available_channels = getattr(dev, "available_input_routing_channels", None)
        if available_channels is None:
            raise NotImplementedError(
                f"device exposes input_routing_type but not "
                f"input_routing_channel — cannot set channel_display_name"
            )
        matched_channel = _find_routing_by_display_name(
            available_channels, channel_display_name
        )
        if matched_channel is None:
            raise ValueError(
                f"input routing channel {channel_display_name!r} not in "
                f"available channels "
                f"{_enumerate_available(available_channels)!r}"
            )
        dev.input_routing_channel = matched_channel

    result: dict[str, Any] = {
        "device_index": device_index,
        "input_routing_type": type_display_name,
        "parent_kind": kind,
    }
    if matched_channel is not None:
        result["input_routing_channel"] = channel_display_name
    result.update(_parent_address(kind, idx))
    return result


def get_input_routing_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Read a device's input routing surface.

    Returns the current selection AND the available enums, so agents can
    discover what's configurable before attempting a write. Returns a
    ``has_input_routing: False`` flag (instead of raising) when the
    device doesn't expose the API — symmetric with capability probing.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    available_types = getattr(dev, "available_input_routing_types", None)
    current_type = getattr(dev, "input_routing_type", None)
    available_channels = getattr(dev, "available_input_routing_channels", None)
    current_channel = getattr(dev, "input_routing_channel", None)

    has_routing = available_types is not None
    result: dict[str, Any] = {
        "device_index": device_index,
        "has_input_routing": has_routing,
        "parent_kind": kind,
    }
    if has_routing:
        result["current_type"] = (
            getattr(current_type, "display_name", None)
            if current_type is not None else None
        )
        result["available_types"] = _enumerate_available(available_types)
        result["current_channel"] = (
            getattr(current_channel, "display_name", None)
            if current_channel is not None else None
        )
        result["available_channels"] = _enumerate_available(available_channels)
    result.update(_parent_address(kind, idx))
    return result


def capabilities_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Structured snapshot of what a device supports.

    Single-call probe that summarizes the device's API surface so an
    agent can decide what to do with it without firing multiple
    introspect calls. Returns a stable shape across every device class
    (Live natives + third-party plugins).
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)

    parameters = getattr(dev, "parameters", ())
    param_names = [p.name for p in parameters]
    sidechain_param_names = [n for n in param_names if _looks_like_sidechain_param(n)]

    class_name = getattr(dev, "class_name", None)
    class_display_name = getattr(dev, "class_display_name", None)
    # PluginDevice / AuPluginDevice are Live's third-party wrappers.
    is_third_party = bool(
        class_name and (
            "Plugin" in class_name
            or class_name in ("PluginDevice", "AuPluginDevice", "Vst3PluginDevice")
        )
    )

    result: dict[str, Any] = {
        "device_index": device_index,
        "class_name": class_name,
        "class_display_name": class_display_name,
        "is_third_party_plugin": is_third_party,
        "parameter_count": len(parameters),
        "sidechain_param_names": sidechain_param_names,
        "has_input_routing": (
            getattr(dev, "available_input_routing_types", None) is not None
        ),
        "can_have_chains": bool(getattr(dev, "can_have_chains", False)),
        "can_have_drum_pads": bool(getattr(dev, "can_have_drum_pads", False)),
        "is_active": bool(getattr(dev, "is_active", True)),
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


def set_sidechain_handler(
    context: LiveContext,
    *,
    device_index: int,
    enabled: bool,
    track_index: int | None = None,
    return_index: int | None = None,
    source_display_name: str | None = None,
    gain_db: float | None = None,
) -> dict[str, Any]:
    """Configure sidechain on any device that exposes the standard
    S/C parameter family — Live natives (Compressor, Compressor2, Glue
    Compressor, Gate, Multiband Dynamics) AND third-party plugins that
    use the same naming pattern.

    Convenience wrapper that delegates to the primitives:
      - source routing via set_input_routing (when source_display_name
        given AND the device exposes input_routing_*)
      - sidechain enable / gain via set_parameter on the discovered
        ``S/C On`` / ``S/C Gain`` (or substring variants)

    Raises a structured teaching error when capabilities are missing —
    no class whitelist, no fictional attributes. Third-party plugins
    with non-canonical naming should configure via
    set_parameter directly after discovery via get_parameters.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)

    # Find sidechain enable + gain params by substring match. Native Live
    # devices: 'S/C On' / 'S/C Gain'. Naming variants captured by the
    # substring hints (caller can also use set_parameter directly).
    enable_param = None
    gain_param = None
    for p in getattr(dev, "parameters", ()):
        lname = (p.name or "").lower()
        if enable_param is None and (
            "s/c on" in lname
            or "sidechain on" in lname
            or "sidechain active" in lname
            or "side enable" in lname
            or "external sidechain" in lname
        ):
            enable_param = p
        if gain_param is None and (
            "s/c gain" in lname
            or "sidechain gain" in lname
            or "side gain" in lname
        ):
            gain_param = p

    if enable_param is None:
        class_name = getattr(dev, "class_name", "<unknown>")
        raise NotImplementedError(
            f"set_sidechain: device {class_name!r} exposes no canonical "
            "sidechain-enable parameter (no S/C On / Sidechain On / "
            "External Sidechain found). For third-party plugins with "
            "non-canonical naming, call ableton_device(action="
            "'get_parameters') to discover names, then "
            "ableton_device(action='set_parameter') directly. For the "
            "source-routing primitive, use ableton_device(action="
            "'set_input_routing')."
        )

    # Toggle enable.
    enable_param.value = 1.0 if enabled else 0.0

    routing_result: dict[str, Any] | None = None
    if enabled and source_display_name is not None:
        # Delegate source routing to the primitive; bubbles its teaching
        # error if the device lacks input_routing_*.
        routing_result = set_input_routing_handler(
            context,
            device_index=device_index,
            track_index=track_index,
            return_index=return_index,
            type_display_name=source_display_name,
        )

    if gain_db is not None:
        if gain_param is None:
            class_name = getattr(dev, "class_name", "<unknown>")
            raise NotImplementedError(
                f"set_sidechain: device {class_name!r} has a sidechain-"
                "enable param but no canonical gain param (no S/C Gain "
                "found). Set gain via ableton_device(action='set_parameter') "
                "after discovering the right name with get_parameters."
            )
        gain_param.value = float(gain_db)

    result: dict[str, Any] = {
        "device_index": device_index,
        "enabled": enabled,
        "enable_param_name": enable_param.name,
        "parent_kind": kind,
    }
    if routing_result is not None:
        result["input_routing_type"] = routing_result.get("input_routing_type")
    if gain_db is not None:
        result["gain_db"] = float(gain_db)
        if gain_param is not None:
            result["gain_param_name"] = gain_param.name
    result.update(_parent_address(kind, idx))
    return result


def get_routing_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Read a device's input routing summary.

    Retained as the legacy-named action. Returns the input_routing_type
    display_name (or None if device lacks the API). The previous
    ``sidechain_active`` field has been retired — it referenced an
    attribute that doesn't exist on real Live devices. Use
    ``capabilities`` for a fuller picture, or ``get_input_routing`` for
    the routing surface including available enums.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    rt = getattr(dev, "input_routing_type", None)
    routing_name = getattr(rt, "display_name", None) if rt is not None else None
    result: dict[str, Any] = {
        "device_index": device_index,
        "input_routing": routing_name,
        "has_input_routing": (
            getattr(dev, "available_input_routing_types", None) is not None
        ),
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


_PRESET_DIRECTIONS = ("next", "previous", "current")


def navigate_preset_handler(
    context: LiveContext,
    *,
    device_index: int,
    direction: str,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Step a device's preset within its browser folder.

    Live exposes ``device.selected_preset_index`` plus methods like
    ``next_preset`` / ``previous_preset`` on some device classes. This
    handler is best-effort: ``current`` just reads the index, ``next`` /
    ``previous`` step it.
    """
    if direction not in _PRESET_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {list(_PRESET_DIRECTIONS)}, got "
            f"{direction!r}"
        )
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    if direction == "current":
        index_now = getattr(dev, "selected_preset_index", None)
        name_now = getattr(dev, "selected_preset_name", None)
        result: dict[str, Any] = {
            "device_index": device_index,
            "direction": direction,
            "preset_index": index_now,
            "preset_name": name_now,
            "parent_kind": kind,
        }
        result.update(_parent_address(kind, idx))
        return result
    step_fn = getattr(
        dev, "next_preset" if direction == "next" else "previous_preset", None
    )
    if step_fn is None:
        raise NotImplementedError(
            f"device {device_index} does not support preset navigation "
            f"({direction!r})"
        )
    step_fn()
    result = {
        "device_index": device_index,
        "direction": direction,
        "preset_index": getattr(dev, "selected_preset_index", None),
        "preset_name": getattr(dev, "selected_preset_name", None),
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


def pad_info_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Read drum-rack pad layout: pitch → chain identity.

    Drum racks (Live's DrumGroupDevice) expose 128 ``drum_pads`` keyed by
    MIDI note number. Each pad has a chain (possibly empty). This handler
    returns the non-empty pads as a list of {note, name, chain_name}.

    On a non-drum-rack device this raises a teaching error.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    pads = getattr(dev, "drum_pads", None)
    if pads is None:
        raise NotImplementedError(
            f"device {device_index} ({getattr(dev, 'class_name', '?')}) is "
            "not a drum rack; pad_info only applies to DrumGroupDevice"
        )
    pads_out: list[dict[str, Any]] = []
    for pad in pads:
        # Live's pad iteration is sometimes by-attribute; treat the
        # collection as an iterable and read fields defensively.
        note = getattr(pad, "note", None)
        chain_name = None
        chains = getattr(pad, "chains", ())
        if chains:
            chain_name = getattr(chains[0], "name", None)
        if chain_name is None and not chains:
            continue  # empty pad
        pads_out.append({
            "note": note,
            "name": getattr(pad, "name", ""),
            "chain_name": chain_name,
        })
    result: dict[str, Any] = {
        "device_index": device_index,
        "pads": pads_out,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


# ---------------------------------------------------------------------------
# Nested rack chains (W6-I/W6-J)
#
# Live's rack devices (InstrumentGroupDevice, AudioEffectGroupDevice,
# DrumGroupDevice) own nested device chains. Each chain has its own
# device list, mixer, and (for drum-rack pads) a parent DrumPad. The
# unified Live API for rack chains:
#   rack_device.chains -> tuple[Chain] (always present on rack devices)
#   drum_rack.drum_pads -> tuple[DrumPad] (drum racks only; each pad
#       has .chains, but typically just one chain per pad)
#   Chain.devices -> tuple[Device] (the nested device list)
#   Chain.name -> str
#   Chain.mixer_device -> ChainMixerDevice (volume, panning, sends, etc.)
#
# W6-I/J expose three actions:
#   get_device_chains — read-only probe; lists the nested structure
#   load_in_rack — load a device into a specific nested chain
#   set_parameter_in_rack — write a parameter on a nested device
#
# These do NOT recurse into nested-nested racks. The schema supports it
# (device_chains.parent_rack_device_id can chain), but the agent surface
# is one-level-deep for now — recursive racks would require addressing
# beyond what (chain_index, device_index) supports. Filed as a future
# backlog item.
# ---------------------------------------------------------------------------


def _resolve_rack_chains(dev: Any) -> tuple[Any, ...]:
    """Return the nested chains of a rack device.

    For Instrument/Audio Effect Group Devices: ``device.chains`` is the
    canonical list. For Drum Group Devices: ``device.chains`` flattens
    every non-empty pad's chain (Live exposes both
    ``drum_rack.chains`` and ``drum_rack.drum_pads[N].chains``; the
    flattened list is what `chains` gives). Raises a teaching error
    on non-rack devices.
    """
    chains = getattr(dev, "chains", None)
    if chains is None:
        class_name = getattr(dev, "class_name", "<unknown>")
        raise NotImplementedError(
            f"device {class_name!r} is not a rack device — has no `chains` "
            "collection. Rack-only actions (get_device_chains, "
            "load_in_rack, set_parameter_in_rack) apply only to "
            "InstrumentGroupDevice, AudioEffectGroupDevice, and "
            "DrumGroupDevice."
        )
    return tuple(chains)


def _resolve_chain_by_index(chains: tuple[Any, ...], chain_index: int) -> Any:
    if chain_index < 1 or chain_index > len(chains):
        raise IndexError(
            f"chain_index {chain_index} out of range [1, {len(chains)}]"
        )
    return chains[chain_index - 1]


def get_device_chains_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
    detail: str = "summary",
) -> dict[str, Any]:
    """Probe a rack device's nested chains.

    Returns ``{device_index, chains: [{chain_index, name, devices:
    [{position, name, class_name, ...}]}], ...}``. With
    ``detail='summary'`` the device entries are identity-only (name +
    class_name + parameter_count + is_active); with ``detail='full'``
    each device also gains its mixer state (volume / panning) and
    chain-mute / chain-solo flags.

    Raises a teaching error on non-rack devices via `_resolve_rack_chains`.
    """
    if detail not in ("summary", "full"):
        raise ValueError(f"detail must be 'summary' or 'full', got {detail!r}")
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    chains = _resolve_rack_chains(dev)

    chains_out: list[dict[str, Any]] = []
    for ci, chain in enumerate(chains, start=1):
        chain_devices = list(getattr(chain, "devices", ()) or ())
        devices_out: list[dict[str, Any]] = []
        for di, cd in enumerate(chain_devices, start=1):
            entry: dict[str, Any] = {
                "position": di,
                "name": getattr(cd, "name", ""),
                "class_name": getattr(cd, "class_name", ""),
                # Arc 4 / D4: browser display name on nested devices — drives
                # `devices.kind` when pull ingests nested rack-chain probes.
                "class_display_name": getattr(cd, "class_display_name", None),
                "parameter_count": len(getattr(cd, "parameters", ())),
                "is_active": bool(getattr(cd, "is_active", True)),
            }
            if detail == "full":
                cd_mixer = getattr(cd, "mixer_device", None)
                if cd_mixer is not None:
                    vol = getattr(cd_mixer, "volume", None)
                    pan = getattr(cd_mixer, "panning", None)
                    entry["mixer"] = {
                        "volume": float(vol.value) if vol is not None else None,
                        "panning": float(pan.value) if pan is not None else None,
                    }
            devices_out.append(entry)
        chain_mixer = getattr(chain, "mixer_device", None)
        chain_entry: dict[str, Any] = {
            "chain_index": ci,
            "name": getattr(chain, "name", ""),
            "device_count": len(chain_devices),
            "devices": devices_out,
            "is_muted": bool(getattr(chain, "mute", False)),
            "is_soloed": bool(getattr(chain, "solo", False)),
        }
        if detail == "full" and chain_mixer is not None:
            vol = getattr(chain_mixer, "volume", None)
            pan = getattr(chain_mixer, "panning", None)
            chain_entry["mixer"] = {
                "volume": float(vol.value) if vol is not None else None,
                "panning": float(pan.value) if pan is not None else None,
            }
        chains_out.append(chain_entry)
    result: dict[str, Any] = {
        "device_index": device_index,
        "class_name": getattr(dev, "class_name", ""),
        "chain_count": len(chains_out),
        "chains": chains_out,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


def load_in_rack_handler(
    context: LiveContext,
    *,
    device_index: int,
    chain_index: int,
    kind: str,
    track_index: int | None = None,
    return_index: int | None = None,
    preset_uri: str | None = None,
) -> dict[str, Any]:
    """Load a device into a specific nested chain of a rack device.

    Uses the same `application.browser.load_item` mechanism as the
    top-level load_handler, but selects the destination CHAIN via
    `song.view.selected_chain = chain` (or, if Live doesn't expose
    `selected_chain` on the View, the chain's `mixer_device.is_active`
    path serves the same purpose). The new device appears at the END
    of the chain's device list — Live exposes no public reorder API
    for nested chains either.

    Raises a teaching error if the parent device isn't a rack, or if
    Live can't bind the chain as the load destination.
    """
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be a non-empty Live device class name")
    parent, parent_kind, parent_idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    rack = _resolve_device(parent, device_index)
    chains = _resolve_rack_chains(rack)
    chain = _resolve_chain_by_index(chains, chain_index)

    application = getattr(context, "application", None)
    if application is None:
        raise NotImplementedError(
            "LiveContext.application is unreachable — browser cannot be "
            "opened for rack-chain load"
        )
    browser = getattr(application, "browser", None)
    if browser is None:
        raise NotImplementedError(
            "application.browser not exposed in this Live version"
        )

    item = _find_browser_item(browser, kind=kind, preset_uri=preset_uri)
    if item is None:
        if preset_uri is not None:
            criteria = f"preset_uri={preset_uri!r}"
        else:
            criteria = _format_kind_failure_criteria(kind)
        raise ValueError(
            f"no loadable browser item found for {criteria}; verify via "
            "ableton_browser(action='tree', ...) or pass preset_uri from "
            "ableton_browser(action='at_path', ...)"
        )

    view = getattr(context.song, "view", None)
    if view is None:
        raise NotImplementedError(
            "song.view not exposed — cannot select destination chain for "
            "browser.load_item"
        )
    # Live's chain-selection API: `selected_chain` exists on the view of
    # rack devices (`rack.view.selected_chain`) in Live 10+. Drum racks
    # also expose `selected_drum_pad`. Set selected_chain directly on the
    # rack's view if available; fall back to song.view.selected_track for
    # the parent track + setting selected_chain on the rack's view.
    rack_view = getattr(rack, "view", None)
    if rack_view is None or not hasattr(rack_view, "selected_chain"):
        raise NotImplementedError(
            f"rack device {getattr(rack, 'class_name', '?')!r} doesn't "
            "expose view.selected_chain — Live's nested-chain load path "
            "is gated on this surface. Drum-rack pads can be selected via "
            "view.selected_drum_pad; instrument/effect racks expose "
            "view.selected_chain. If your Live version differs, file an "
            "issue with the empirical probe (capabilities action + "
            "introspect on the rack device)."
        )
    chain_before = len(chain.devices)
    rack_view.selected_chain = chain
    # Also select the parent track so the browser-load fires in the right
    # context — Live's browser.load_item routes through the highlighted
    # surface chain.
    view.selected_track = parent
    browser.load_item(item)

    fresh_rack = _refresh_parent(
        context, parent_kind=parent_kind, parent_idx=parent_idx
    ).devices[device_index - 1]
    fresh_chains = _resolve_rack_chains(fresh_rack)
    fresh_chain = _resolve_chain_by_index(fresh_chains, chain_index)
    chain_after = list(fresh_chain.devices)
    if len(chain_after) <= chain_before:
        raise RuntimeError(
            f"load_in_rack: Live did not append a device on chain "
            f"{chain_index} of rack {device_index} after browser.load_item; "
            "the item may not be loadable on this rack type, or the "
            "chain-selection step didn't take effect"
        )
    new_device = chain_after[-1]
    result: dict[str, Any] = {
        "device_index": device_index,
        "chain_index": chain_index,
        "nested_device_position": len(chain_after),
        "kind": kind,
        "name": getattr(new_device, "name", ""),
        "parent_kind": parent_kind,
    }
    if preset_uri is not None:
        result["preset_uri"] = preset_uri
    result.update(_parent_address(parent_kind, parent_idx))
    return result


def set_parameter_in_rack_handler(
    context: LiveContext,
    *,
    device_index: int,
    chain_index: int,
    nested_device_position: int,
    parameter_name: str,
    value: str,
    track_index: int | None = None,
    return_index: int | None = None,
    value_type: str = "continuous",
) -> dict[str, Any]:
    """Write a parameter on a device inside a rack's nested chain.

    Addresses the parameter via (rack device_index, chain_index,
    nested_device_position, parameter_name). Reuses the
    continuous-vs-enum dispatch logic from set_parameter_handler so
    the write semantics match exactly. Value is schema-permissive (str)
    and coerced per value_type — mirrors set_parameter.
    """
    if value_type not in ("continuous", "enum"):
        raise ValueError(
            f"value_type must be 'continuous' or 'enum', got {value_type!r}"
        )
    parent, parent_kind, parent_idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    rack = _resolve_device(parent, device_index)
    chains = _resolve_rack_chains(rack)
    chain = _resolve_chain_by_index(chains, chain_index)
    chain_devices = list(getattr(chain, "devices", ()) or ())
    if nested_device_position < 1 or nested_device_position > len(chain_devices):
        raise IndexError(
            f"nested_device_position {nested_device_position} out of range "
            f"[1, {len(chain_devices)}] on chain {chain_index}"
        )
    nested_device = chain_devices[nested_device_position - 1]
    param = None
    for p in getattr(nested_device, "parameters", ()):
        if p.name == parameter_name:
            param = p
            break
    if param is None:
        available = [p.name for p in getattr(nested_device, "parameters", ())]
        raise ValueError(
            f"parameter {parameter_name!r} not found on nested device "
            f"{nested_device_position}; available: {available}"
        )

    if value_type == "enum":
        items = tuple(getattr(param, "value_items", ()) or ())
        if not items:
            raise ValueError(
                f"parameter {parameter_name!r} on nested device "
                f"{nested_device_position} is not a quantized enum"
            )
        try:
            idx = items.index(value)
        except ValueError:
            raise ValueError(
                f"enum value {value!r} not in {parameter_name!r}'s value_items {list(items)!r}"
            ) from None
        param.value = float(idx)
        result: dict[str, Any] = {
            "device_index": device_index,
            "chain_index": chain_index,
            "nested_device_position": nested_device_position,
            "parameter_name": parameter_name,
            "value_type": value_type,
            "value": value,
            "parent_kind": parent_kind,
        }
    else:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"value_type='continuous' requires a numeric value (parseable as float); "
                f"got {value!r}"
            ) from None
        param.value = numeric
        result = {
            "device_index": device_index,
            "chain_index": chain_index,
            "nested_device_position": nested_device_position,
            "parameter_name": parameter_name,
            "value_type": value_type,
            "value": numeric,
            "parent_kind": parent_kind,
        }
    result.update(_parent_address(parent_kind, parent_idx))
    return result


__all__ = [
    "list_handler",
    "info_handler",
    "get_parameters_handler",
    "load_handler",
    "delete_handler",
    "enable_handler",
    "disable_handler",
    "set_parameter_handler",
    "set_sidechain_handler",
    "set_input_routing_handler",
    "get_input_routing_handler",
    "capabilities_handler",
    "get_routing_handler",
    "navigate_preset_handler",
    "pad_info_handler",
    "get_device_chains_handler",
    "load_in_rack_handler",
    "set_parameter_in_rack_handler",
]
