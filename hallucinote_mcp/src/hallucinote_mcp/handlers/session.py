"""Imperative handlers for ``ableton_session`` actions.

The simple actions (set_tempo, set_view, play, stop, etc.) are declarative
ops on the Live API and live in ``actions/session.py`` as ``LiveOp`` entries.
The handlers in this module cover the actions that need real Python:

  - ``info``: read multiple Live properties, assemble a structured dict.
  - ``bout_status`` / ``abandon_bout``: read (and, as a last resort, release)
    the main-thread occupancy record. Both run on the WORKER thread — see
    their handlers.
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
from .jobs import JobRegistry, default_registry
from ._transport import locate_start_position
from ._arrangement_latch import (
    CLICK_BACK_TO_ARRANGEMENT,
    OVERRIDE_DESCRIPTION,
    is_overridden,
)


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

    overridden = is_overridden(song)
    snapshot: dict[str, Any] = {
        "tempo": float(song.tempo),
        "signature": {
            "numerator": int(song.signature_numerator),
            "denominator": int(song.signature_denominator),
        },
        "is_playing": bool(song.is_playing),
        "current_song_time": float(song.current_song_time),
        # The Arrangement-override latch. A bare ``True`` here is the silent
        # cause of "transport moving, no audio" — so when it is engaged we
        # also surface a named, recoverable state rather than leaving the
        # agent to interpret the bool (MCP-7P3R direction 4).
        "back_to_arranger": overridden,
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
    if overridden:
        snapshot["arrangement_override"] = {
            "latched": True,
            "note": (
                f"{OVERRIDE_DESCRIPTION} {CLICK_BACK_TO_ARRANGEMENT} "
                f"ableton_session(action='back_to_arrangement') attempts the "
                f"API clear and reports whether Live honored it."
            ),
        }
    bout = _bout_block(context)
    if bout is not None:
        snapshot["main_thread_bout"] = bout
    return snapshot


def _bout_block(context: LiveContext) -> dict[str, Any] | None:
    """The main-thread occupancy record, or ``None`` when Live is free.

    Read tolerantly: ``info`` is exercised against many minimal context
    doubles, and a double that predates the occupancy record must yield a
    snapshot without the block rather than an AttributeError. The record is
    the visible half of "a never-signalling runner is never silently cleared".

    Note that ``info`` itself is main-thread-wrapped, so a caller that reaches
    this handler at all has been ADMITTED — which is why the block is normally
    absent, and why ``bout_status`` (worker-thread) is the surface that can
    still answer while the fence is closed. This block covers the case a
    worker-thread caller can't: reading occupancy from inside a nested bout.
    """
    reader = getattr(context, "main_thread_bout", None)
    if reader is None:
        return None
    bout = reader()
    return bout if isinstance(bout, dict) else None


# ---------------------------------------------------------------------------
# bout_status / abandon_bout — the main-thread occupancy surface
# ---------------------------------------------------------------------------


def bout_status_handler(
    context: LiveContext,
    *,
    job_id: str | None = None,
    _registry: JobRegistry | None = None,
) -> dict[str, Any]:
    """Report what Live's main thread is occupied with, and poll an escalated
    bout's job.

    Runs on the WORKER thread (``runs_on_worker=True``). It has to: an action
    that took a main-thread bout in order to ask about the main-thread bout
    would be refused by the very fence it exists to report on, and would
    deadlock by construction while a bout was escalated.

    With ``job_id``, also returns that job's record — ``state`` is
    ``running`` until Live's main thread finally returns, then ``done`` (with
    the call's ``result``) or ``failed``. Without one, reports occupancy only,
    which is the read a caller has when it never received a handle.
    """
    occupied = _bout_block(context)
    out: dict[str, Any] = {"occupied": occupied is not None}
    if occupied is not None:
        out["main_thread_bout"] = occupied
    if job_id is None:
        if occupied is None:
            out["message"] = (
                "Live's main thread is free — no operation is holding the "
                "admission gate."
            )
        return out
    registry = _registry if _registry is not None else default_registry()
    job = registry.get(job_id)
    if job is None:
        recent = registry.recent_ids(kind="main_thread")
        hint = (
            f"recent escalated bouts: {', '.join(recent)}"
            if recent
            else "no main-thread work has been escalated in this Live session"
        )
        raise ValueError(f"bout_status: unknown job_id {job_id!r} ({hint})")
    out["job"] = job.status_result()
    return out


def abandon_bout_handler(context: LiveContext, *, job_id: str) -> dict[str, Any]:
    """Force-release the admission gate held by an escalated bout.

    Runs on the WORKER thread for the same reason as ``bout_status``.

    This does NOT cancel anything — a Live API call cannot be interrupted. It
    marks the job ``failed`` (nothing will ever settle it now) and reopens
    admission, accepting that whatever comes next may queue behind work Live
    is still doing. It exists because the alternative — a timed auto-clear —
    would silently re-create the defect the fence exists to prevent.
    """
    abandon = getattr(context, "abandon_main_thread_bout", None)
    if abandon is None:
        raise ValueError(
            "abandon_bout: this Live context does not track main-thread "
            "occupancy, so there is no gate to release. Re-vendor the Remote "
            "Script and restart Live."
        )
    return abandon(job_id)


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
    """Move the transport to (bar, beat). 1-based bar, 0-based-within-bar beat.

    Moves Live's **start playing position**, not only the playhead. Those are
    separate, and ``start_playing()`` rolls from the first while writing
    ``current_song_time`` moves only the second — so a seek that moved only the
    playhead read back perfectly and then played from wherever the operator had
    last pressed play. Anyone using seek-then-play to inspect a position (the
    read-back workflow that diagnosed #471) needs the strong one. See
    ``handlers/_transport.py``.

    ``start_position_moved`` says whether that succeeded; ``locate_method``
    says how, and ``locate_detail`` says why not when it is False. A degraded
    locate still leaves the playhead where it was asked — it just cannot
    promise playback will begin there.

    Returns the COMPUTED ``song_time`` from the input, not a getter-readback.
    Live 12.x's ``Song.current_song_time`` getter can return a stale cached
    value within the same callback as the setter (the audio thread picks
    up writes on a delayed schedule); reporting the readback gave false
    response values like ``song_time=last_event_time`` when the readback
    raced the write. ``settled_beats`` carries what the position actually
    settled to, which is a different fact and is polled for, not raced.

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
    def _compute_song_time_on_main() -> float:
        song = context.song
        beats_per_bar = float(song.signature_numerator) * (
            4.0 / float(song.signature_denominator)
        )
        return float((bar - 1) * beats_per_bar + beat)

    with context.live_state_lock:
        song_time = context.run_on_main(_compute_song_time_on_main)
        locate = locate_start_position(context, song_time)
    result: dict[str, Any] = {
        "bar": bar,
        "beat": beat,
        "song_time": song_time,
        "settled_beats": locate.settled_beats,
        "start_position_moved": locate.start_position_moved,
        "locate_method": locate.method,
    }
    if locate.detail is not None:
        result["locate_detail"] = locate.detail
    return result


# ---------------------------------------------------------------------------
# transport: play / continue_playing
#
# Both are handler actions (not declarative LiveOps) so they can return a
# ``verb`` teaching field naming which Live transport verb fired — *Start*
# (play) vs *Continue* (continue_playing). We report the VERB invoked, not a
# read-back of where Live actually began: a handler can't reliably read the
# realized start position back (the audio thread settles ``current_song_time``
# on a delayed schedule — see ``seek_handler``). The common reason a ``seek``
# "doesn't take" is not the transport verb at all but the ``back_to_arranger``
# override latch suppressing Arrangement playback (MCP-7P3R directions 2 + 4 —
# the recovery is ``back_to_arrangement``). The dispatcher runs these on the
# main thread.
# ---------------------------------------------------------------------------

_PLAY_SEMANTICS_NOTE = (
    "play invokes Live's *Start*; continue_playing invokes *Continue* (resume "
    "from the last-stopped position). This result reports the verb invoked, NOT "
    "a read-back of where Live actually began — the realized start position is "
    "Live-state-dependent and a handler can't reliably read it back. Both verbs "
    "roll from Live's START PLAYING POSITION, which is a different property "
    "from the playhead: writing current_song_time moves the playhead alone, so "
    "a raw seek-then-play begins wherever play was last pressed. "
    "ableton_session(action='seek') moves the start position too and reports "
    "start_position_moved, so use it rather than writing the playhead directly. "
    "If the transport moves but you hear no audio, the usual cause is the "
    "back_to_arranger override latch suppressing Arrangement playback; clear it "
    "with ableton_session(action='back_to_arrangement')."
)


def play_handler(context: LiveContext) -> dict[str, Any]:
    """Start playback (Live's *Start* transport verb)."""
    context.song.start_playing()
    return {
        "is_playing": True,
        "verb": "start",
        "note": _PLAY_SEMANTICS_NOTE,
    }


def continue_playing_handler(context: LiveContext) -> dict[str, Any]:
    """Resume playback (Live's *Continue* transport verb).

    *Continue* resumes from the last-stopped position. The result names the
    verb invoked, not the realized start position (see ``_PLAY_SEMANTICS_NOTE``).
    """
    context.song.continue_playing()
    return {
        "is_playing": True,
        "verb": "continue",
        "note": _PLAY_SEMANTICS_NOTE,
    }


# ---------------------------------------------------------------------------
# back_to_arrangement — recover from a Session-clip override of the Arrangement
# ---------------------------------------------------------------------------


def back_to_arrangement_handler(context: LiveContext) -> dict[str, Any]:
    """Re-engage Arrangement playback after a Session clip overrode a track.

    Does what Live's **Back to Arrangement** button does — clears the global
    ``back_to_arranger`` latch and re-enables any overridden automation — then
    reads the latch back and reports honestly whether Live honored it. In Live
    12.x the property write is silently ignored (a LOM quirk, not a threading
    one — this handler already runs on the main thread), so the API clear may
    not stick; when it doesn't, we return ``cleared: False`` with a teaching
    ``warning`` naming the GUI button rather than a misleading ``ok``. (Direction
    1 of MCP-7P3R.)
    """
    song = context.song
    if not is_overridden(song):
        return {
            "cleared": True,
            "was_latched": False,
            "note": "Arrangement was not overridden — nothing to recover.",
        }

    # Best-effort, mirroring the GUI button. Both reads/writes are already on
    # the main thread (this handler is not runs_on_worker).
    try:
        song.back_to_arranger = 0
    except (AttributeError, RuntimeError):
        pass
    re_enable = getattr(song, "re_enable_automation", None)
    if callable(re_enable):
        re_enable()

    if not is_overridden(song):
        return {"cleared": True, "was_latched": True}
    return {
        "cleared": False,
        "was_latched": True,
        "warning": (
            f"Live did not honor the API clear: back_to_arranger is still "
            f"latched after setting it to 0 and calling re_enable_automation. "
            f"{CLICK_BACK_TO_ARRANGEMENT}"
        ),
    }


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
    "play_handler",
    "continue_playing_handler",
    "back_to_arrangement_handler",
    "set_signature_handler",
    "set_view_handler",
    "snapshot_handler",
    "revert_handler",
    "list_snapshots_handler",
    "introspect_handler",
]
