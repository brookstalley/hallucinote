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
        "focused_view": _focused_view(song),
    }


def _focused_view(song: Any) -> str:
    """Return one of the top-level view labels currently shown by Live.

    Reads via ``song.get_application().view`` — the same surface that
    ``set_view_handler`` writes to, so reads and writes are symmetric. If the
    application object isn't reachable (older Live builds, weird embeddings),
    returns ``"unknown"`` rather than leaking unrelated state into the field.
    """
    try:
        application = song.get_application()
        view = application.view
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
    """Move the playhead to (bar, beat). 1-based bar, 0-based-within-bar beat."""
    song = context.song
    beats_per_bar = float(song.signature_numerator) * (
        4.0 / float(song.signature_denominator)
    )
    song.current_song_time = (bar - 1) * beats_per_bar + beat
    return {"bar": bar, "beat": beat, "song_time": float(song.current_song_time)}


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

    Live's view system lives at ``Application.View``, not on the song. The
    handler asks the Application object for its view, then calls
    ``show_view(<live-name>)``.
    """
    live_name = _VIEW_NAMES.get(view)
    if live_name is None:
        raise ValueError(
            f"set_view: view {view!r} not recognized; "
            f"valid values are {sorted(_VIEW_NAMES)}"
        )
    song = context.song
    application = song.get_application()  # Live's standard accessor
    application.view.show_view(live_name)
    return {"view": view, "live_view_name": live_name}


__all__ = [
    "info_handler",
    "set_master_property_handler",
    "seek_handler",
    "set_signature_handler",
    "set_view_handler",
    "snapshot_handler",
    "revert_handler",
    "list_snapshots_handler",
]
