"""Imperative handlers for ``ableton_session`` actions.

The simple actions (set_tempo, set_view, play, stop, etc.) are declarative
ops on the Live API and live in ``actions/session.py`` as ``LiveOp`` entries.
The handlers in this module cover the actions that need real Python:

  - ``info``: read multiple Live properties, assemble a structured dict.
  - ``set_master_property``: branch on the ``property`` value to choose the
    correct Live API target (master_track.mixer_device.volume vs panning vs ...).
  - ``set_arrangement_loop``: 3 properties (enabled / start / length) touched
    in one call; bar-to-beat conversion for start/end.
  - ``seek``: bar-to-beat conversion using the current signature.
  - ``set_signature``: writes both numerator and denominator on the master
    signature object.
  - ``snapshot`` / ``revert`` / ``list_snapshots``: stubbed in M-1 — schema is
    stable but execution is "blocked, pending design pass" per design doc §14.6
    (snapshot semantics — Live undo checkpoint vs ``.als`` save-as is an open
    design question). Backlog item tracks the deferred implementation.

Every handler signature is ``handler(context, **validated_params) -> result``.
The dispatcher invokes them on Live's main thread (atomically with the
``run_on_main`` bounce) so they can touch ``context.song`` freely.
"""
from __future__ import annotations

import re as _re
from typing import Any

from ..dispatcher import LiveContext


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


def info_handler(context: LiveContext) -> dict[str, Any]:
    """Assemble a structured snapshot of session-global state.

    Returns a dict with: tempo, signature, transport state, current song
    time, arrangement loop, master mixer, focused view, plus counts for
    tracks / returns / scenes (cheap reads — full enumerations belong on
    each domain's tool).
    """
    song = context.song
    master = song.master_track
    master_mixer = master.mixer_device

    return {
        "tempo": float(song.tempo),
        "signature": {
            "numerator": int(song.signature_numerator),
            "denominator": int(song.signature_denominator),
        },
        "is_playing": bool(song.is_playing),
        "current_song_time": float(song.current_song_time),
        "loop": {
            "enabled": bool(song.loop),
            "start": float(song.loop_start),
            "length": float(song.loop_length),
        },
        "master": {
            "volume": float(master_mixer.volume.value),
            "panning": float(master_mixer.panning.value),
        },
        "track_count": len(song.tracks),
        "return_count": len(song.return_tracks),
        "scene_count": len(song.scenes),
        "focused_view": _focused_view(context),
    }


def _focused_view(context: LiveContext) -> str:
    """Return one of the top-level view labels currently shown by Live.

    Reads via ``context.application.view`` — the same surface that
    ``set_view_handler`` writes to, so reads and writes are symmetric. If the
    application object isn't reachable (older Live builds, weird embeddings),
    returns ``"unknown"`` rather than leaking unrelated state into the field.
    """
    try:
        view = context.application.view
    except (AttributeError, RuntimeError):
        return "unknown"
    for label in ("Session", "Arranger", "Detail/Clip", "Detail/DeviceChain", "Browser"):
        try:
            if view.is_view_visible(label):
                return label
        except (AttributeError, RuntimeError):
            return "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# set_master_property
# ---------------------------------------------------------------------------


# Per-property value bounds. Live silently clamps out-of-range values, so we
# fail loudly instead — a teaching error beats a write that quietly does the
# wrong thing. The schema-level ParamSpec for ``value`` is intentionally
# unranged (one param, three meanings); these per-property checks are the
# semantic enforcement layer.
_MASTER_VALUE_BOUNDS: dict[str, tuple[float, float]] = {
    "volume": (0.0, 1.0),       # Live's normalized scale
    "panning": (-1.0, 1.0),      # -1 = hard left, +1 = hard right
}

_MASTER_TARGETS: dict[str, str] = {
    "volume": "volume",
    "panning": "panning",
}


def set_master_property_handler(
    context: LiveContext, *, property: str, value: float
) -> dict[str, Any]:
    """Write a single master-strip mixer property.

    The Live API exposes master volume/pan as ``MixerDeviceParameter`` objects
    with their own ``value`` attribute; assignment is to the ``value``
    attribute, not the parent. ``mute`` is a plain bool on the track.

    Range validation is per-property (volume 0-1, panning -1..1, mute is
    truthy) — Live would silently clamp otherwise, which hides agent errors.
    """
    if property == "mute":
        # mute accepts any numeric truthiness; no range check beyond that.
        song = context.song
        master = song.master_track
        master.mute = bool(value)
        return {"property": property, "value": bool(value)}
    if property not in _MASTER_TARGETS:
        raise ValueError(
            f"set_master_property: property {property!r} is not supported; "
            f"valid values are {sorted(list(_MASTER_TARGETS) + ['mute'])}"
        )
    lo, hi = _MASTER_VALUE_BOUNDS[property]
    if not (lo <= value <= hi):
        raise ValueError(
            f"set_master_property: value {value} for {property!r} is out of "
            f"range [{lo}, {hi}]"
        )
    song = context.song
    master = song.master_track
    target = getattr(master.mixer_device, _MASTER_TARGETS[property])
    target.value = float(value)
    return {"property": property, "value": float(value)}


# ---------------------------------------------------------------------------
# Arrangement loop — moved to ableton_arrangement(action='set_loop') in
# Wave M-5. See handlers/arrangement.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# seek
# ---------------------------------------------------------------------------


def seek_handler(
    context: LiveContext, *, bar: int, beat: float = 0.0
) -> dict[str, Any]:
    """Move the playhead to (bar, beat). 1-based bar, 0-based-within-bar beat.

    Returns the COMPUTED ``song_time`` from the input, not a getter-readback.
    Live 12.x's ``Song.current_song_time`` getter can return a stale cached
    value within the same callback as the setter (the audio thread picks
    up writes on a delayed schedule); reporting the readback gave false
    response values like ``song_time=last_event_time`` when the readback
    raced the write. The write itself is correct — Live's transport
    eventually settles to the target — so reporting what we wrote is the
    honest answer.

    **Threading (W3-F follow-up):** Registered with ``runs_on_worker=True``.
    Holds ``context.live_state_lock`` around the write to serialize
    against in-flight ``cue_create`` / ``cue_create_batch`` /
    ``cue_delete`` (B-21). The lock is a ``threading.RLock`` — its
    cross-thread acquire semantics REQUIRE all lock takers be on the
    same kind of thread (worker), otherwise we deadlock against
    worker-thread holders. Pre-fix state (main-thread seek_handler
    acquiring a lock held by worker-thread cue_create) was the
    deadlock that the Critic caught.
    """
    def _compute_and_seek_on_main() -> float:
        song = context.song
        beats_per_bar = float(song.signature_numerator) * (
            4.0 / float(song.signature_denominator)
        )
        song_time = (bar - 1) * beats_per_bar + beat
        song.current_song_time = song_time
        return float(song_time)

    with context.live_state_lock:
        song_time = context.run_on_main(_compute_and_seek_on_main)
    return {"bar": bar, "beat": beat, "song_time": song_time}


# ---------------------------------------------------------------------------
# set_signature
# ---------------------------------------------------------------------------


def set_signature_handler(
    context: LiveContext, *, numerator: int, denominator: int
) -> dict[str, Any]:
    """Set the *global* (master) signature. For per-bar meter changes, use
    arrangement-level meter automation (gap-tracked under ``ableton_automation``).
    """
    if denominator not in (1, 2, 4, 8, 16, 32):
        raise ValueError(
            f"set_signature: denominator must be a power of two between 1 and 32, "
            f"got {denominator}"
        )
    song = context.song
    song.signature_numerator = int(numerator)
    song.signature_denominator = int(denominator)
    return {"numerator": int(numerator), "denominator": int(denominator)}


# ---------------------------------------------------------------------------
# snapshot / revert / list_snapshots — stubbed
# ---------------------------------------------------------------------------


_SNAPSHOT_GAP_HINT = (
    "Snapshot semantics are under design — Live undo checkpoint vs `.als` "
    "save-as is an open question (design doc §14.6). Schema is stable; "
    "implementation lands in a follow-up chunk."
)


def snapshot_handler(context: LiveContext, *, name: str) -> dict[str, Any]:
    raise NotImplementedError(_SNAPSHOT_GAP_HINT)


def revert_handler(context: LiveContext, *, name: str) -> dict[str, Any]:
    raise NotImplementedError(_SNAPSHOT_GAP_HINT)


def list_snapshots_handler(context: LiveContext) -> dict[str, Any]:
    raise NotImplementedError(_SNAPSHOT_GAP_HINT)


# ---------------------------------------------------------------------------
# set_view
# ---------------------------------------------------------------------------


# Map agent-friendly lowercase names to Live's view-name constants. Live's
# Application.View.show_view() requires the exact strings on the right.
_VIEW_NAMES: dict[str, str] = {
    "session": "Session",
    "arranger": "Arranger",
    "detail": "Detail/Clip",
    "browser": "Browser",
}


def set_view_handler(context: LiveContext, *, view: str) -> dict[str, Any]:
    """Focus a top-level Live view.

    Live's view system lives at ``Application.View``, not on the song.
    Application access flows through ``LiveContext.application`` so the
    handler doesn't need to import Live directly or reach into Song
    (which doesn't expose ``get_application`` in any Live version we
    target).
    """
    live_name = _VIEW_NAMES.get(view)
    if live_name is None:
        raise ValueError(
            f"set_view: view {view!r} not recognized; "
            f"valid values are {sorted(_VIEW_NAMES)}"
        )
    context.application.view.show_view(live_name)
    return {"view": view, "live_view_name": live_name}


# ---------------------------------------------------------------------------
# introspect (W6-Probe — empirical LOM probing for chunk investigations)
# ---------------------------------------------------------------------------


_INTROSPECT_SEGMENT_RE = _re.compile(r"^([a-zA-Z_][a-zA-Z_0-9]*)(?:\[(\d+)\])?$")
_INTROSPECT_WHAT_KINDS = ("dir", "type", "value", "repr")
_INTROSPECT_PRIMITIVES = (int, float, bool, str, type(None))


def _resolve_introspect_target(context: LiveContext, target: str) -> Any:
    """Walk a dotted path against the LiveContext roots.

    Roots: ``song`` (→ ``context.song``), ``application``
    (→ ``context.application``), ``view`` (→ ``context.application.view``).

    Each segment is ``name`` or ``name[index]``. Index access is 0-based —
    this is RAW Python indexing, NOT the 1-based MCP convention used for
    track_index etc., because the whole point of introspect is an
    unvarnished view of the LOM.

    Read-only: uses ``getattr`` and ``__getitem__`` only — no eval, no
    method invocation. Returns the resolved object for the caller to
    introspect.
    """
    if not isinstance(target, str) or not target.strip():
        raise ValueError("introspect: target must be a non-empty dotted path")
    segments = target.split(".")

    first = _INTROSPECT_SEGMENT_RE.match(segments[0])
    if first is None:
        raise ValueError(
            f"introspect: invalid root segment {segments[0]!r}"
        )
    root_name = first.group(1)
    if root_name == "song":
        obj: Any = context.song
    elif root_name == "application":
        obj = context.application
    elif root_name == "view":
        # `view` is an alias for `application.view` for convenience.
        obj = context.application.view
    else:
        raise ValueError(
            f"introspect: root {root_name!r} not in ['song', 'application', "
            f"'view']"
        )
    if first.group(2) is not None:
        # Indexed root (rare — e.g. `view[0]` doesn't make sense but
        # `song` could conceivably be indexable in some future shape).
        # Apply it uniformly with the rest of the walk.
        obj = _apply_index(obj, int(first.group(2)), at=root_name)

    path_so_far = segments[0]
    for seg in segments[1:]:
        m = _INTROSPECT_SEGMENT_RE.match(seg)
        if m is None:
            raise ValueError(
                f"introspect: invalid path segment {seg!r} in {target!r}; "
                f"expected `name` or `name[index]`"
            )
        attr = m.group(1)
        if not hasattr(obj, attr):
            raise ValueError(
                f"introspect: {path_so_far!r} has no attribute {attr!r}"
            )
        obj = getattr(obj, attr)
        if m.group(2) is not None:
            obj = _apply_index(
                obj, int(m.group(2)), at=f"{path_so_far}.{attr}"
            )
        path_so_far = f"{path_so_far}.{seg}"

    return obj


def _apply_index(container: Any, idx: int, *, at: str) -> Any:
    try:
        return container[idx]
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError(
            f"introspect: index {idx} invalid at {at!r}: {exc}"
        ) from exc


def introspect_handler(
    context: LiveContext,
    *,
    target: str,
    what: str = "dir",
    include_private: bool = False,
) -> dict[str, Any]:
    """Read-only LOM probing — call ``dir()`` / ``type()`` / ``value`` /
    ``repr()`` on a dotted-path target.

    Used to investigate Live's API surface from a conversation when the
    Live 12 LOM XML isn't published or the gluon Remote Scripts repo
    isn't unambiguous. Has no side effects on the song.

    Path syntax: dotted from one of three roots (``song``, ``application``,
    ``view``). Each segment is ``name`` or ``name[index]``. Index is
    0-based RAW Python — NOT the 1-based MCP convention.

    ``what``:
      - ``dir``: list of member names. Private (``_*``) filtered unless
        ``include_private=True``.
      - ``type``: fully-qualified class name (e.g.
        ``Live.Clip.AutomationEnvelope``).
      - ``value``: the value itself if int/float/bool/str/None, else
        ``repr()`` with a ``note`` flag.
      - ``repr``: always ``repr(obj)``.

    Generalized by design (per project memory
    `feedback_generalize_research_first`): one mechanism for any LOM
    object, not a per-class registry.
    """
    if what not in _INTROSPECT_WHAT_KINDS:
        raise ValueError(
            f"introspect: what {what!r} not in {list(_INTROSPECT_WHAT_KINDS)}"
        )

    obj = _resolve_introspect_target(context, target)

    if what == "dir":
        names = sorted(set(dir(obj)))
        if not include_private:
            names = [n for n in names if not n.startswith("_")]
        return {"target": target, "what": what, "members": names}

    if what == "type":
        cls = type(obj)
        module = getattr(cls, "__module__", "") or ""
        qualname = getattr(cls, "__qualname__", cls.__name__)
        type_name = f"{module}.{qualname}" if module and module != "builtins" else qualname
        return {"target": target, "what": what, "type": type_name}

    if what == "value":
        if isinstance(obj, _INTROSPECT_PRIMITIVES):
            return {"target": target, "what": what, "value": obj}
        return {
            "target": target,
            "what": what,
            "value": repr(obj),
            "note": "non-primitive — returned repr()",
        }

    # what == "repr"
    return {"target": target, "what": what, "repr": repr(obj)}


__all__ = [
    "info_handler",
    "set_master_property_handler",
    "seek_handler",
    "set_signature_handler",
    "set_view_handler",
    "snapshot_handler",
    "revert_handler",
    "list_snapshots_handler",
    "introspect_handler",
]
