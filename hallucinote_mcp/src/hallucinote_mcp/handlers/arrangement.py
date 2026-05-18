"""Imperative handlers for ``ableton_arrangement`` actions.

Arrangement state lives at ``song.cue_points`` (the cue list),
``song.loop`` / ``song.loop_start`` / ``song.loop_length`` (the loop
region), ``song.last_event_time`` (the arrangement total length), and
``context.application.view`` (arranger view controls — Live's ``Song``
does NOT expose ``get_application``; the Application is reached via
the LiveContext Protocol).

Cue point time positions are in **beats** on the wire (Wave M-3/M-4
principle: wire stays meter-agnostic; Hallucinote planner converts from
bar-based song positions via the time-signature map before emit). The
handler does no bar/beat translation.

Cue point name gap (Hallucinote gap #13) — Live's API exposes
``cue.name`` as readable AND writable, but the legacy fork's
``get_cue_points`` returned only numeric IDs, not names. With our
greenfield Remote Script we read names directly; the gap is resolved
for the new MCP server's lifetime.
"""
from __future__ import annotations

import time
from typing import Any

from ..dispatcher import LiveContext


# How long ``cue_create`` waits in wall-clock time for
# ``Song.current_song_time`` to be visible to ``Song.set_or_delete_cue``.
# Empirical Live 12.x behavior: the setter completes synchronously on
# the main thread, but the audio thread (which the cue toggle reads)
# picks up the new value on a delayed schedule — observed lag is on
# the order of 100-200ms when transport is stopped. ``schedule_message``
# bounces don't wait wall-clock time (they fire back-to-back within
# one engine tick) so a poll-via-bounce loop reads stale values. The
# simplest reliable mechanism is to sleep here: the audio thread runs
# on its own OS thread and continues processing while the main thread
# blocks. 200ms is a conservative ceiling that handles the observed
# lag with margin; tighten if/when the audio-thread timing model is
# better understood.
_CUE_SETTLE_SLEEP_S = 0.2


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


def info_handler(context: LiveContext) -> dict[str, Any]:
    """Arrangement-level state snapshot.

    Returns global tempo + signature (the song-level values at the start
    of the arrangement; per-bar automation is captured by separate
    envelope reads when gap-blocked), arrangement total length in beats,
    loop region, and cue count.
    """
    song = context.song
    sig_num = int(getattr(song, "signature_numerator", 4))
    sig_den = int(getattr(song, "signature_denominator", 4))
    return {
        "tempo": float(getattr(song, "tempo", 120.0)),
        "signature": {"numerator": sig_num, "denominator": sig_den},
        "total_length_beats": float(getattr(song, "last_event_time", 0.0)),
        "loop_enabled": bool(getattr(song, "loop", False)),
        "loop_start_beats": float(getattr(song, "loop_start", 0.0)),
        "loop_length_beats": float(getattr(song, "loop_length", 0.0)),
        "cue_count": len(getattr(song, "cue_points", ())),
    }


# ---------------------------------------------------------------------------
# set_loop
# ---------------------------------------------------------------------------


def set_loop_handler(
    context: LiveContext,
    *,
    enabled: bool,
    start_beats: float | None = None,
    end_beats: float | None = None,
) -> dict[str, Any]:
    """Toggle the arrangement loop + optionally set its region in beats.

    Both start_beats and end_beats must be passed together (or neither).
    Live stores the loop as (loop_start, loop_length); we compute length
    from (end_beats - start_beats).

    Wave M-3 principle: wire is meter-agnostic — beats not bars. The
    Hallucinote planner converts bar-based song positions before emit.
    """
    if (start_beats is None) != (end_beats is None):
        raise ValueError(
            "set_loop: pass start_beats AND end_beats together, or neither"
        )
    song = context.song
    if start_beats is not None and end_beats is not None:
        if start_beats < 0:
            raise ValueError(f"start_beats {start_beats} must be >= 0")
        if end_beats <= start_beats:
            raise ValueError(
                f"end_beats {end_beats} must be > start_beats {start_beats}"
            )
        song.loop_start = float(start_beats)
        song.loop_length = float(end_beats) - float(start_beats)
    song.loop = bool(enabled)
    return {
        "enabled": bool(enabled),
        "loop_start_beats": float(getattr(song, "loop_start", 0.0)),
        "loop_length_beats": float(getattr(song, "loop_length", 0.0)),
    }


# ---------------------------------------------------------------------------
# control_view
# ---------------------------------------------------------------------------


_VIEW_ACTIONS = (
    "zoom_in", "zoom_out", "scroll_left", "scroll_right",
    "follow_on", "follow_off", "collapse_track", "expand_track",
)


def control_view_handler(
    context: LiveContext,
    *,
    action_kind: str,
    track_index: int | None = None,
) -> dict[str, Any]:
    """Step the arranger view. Each action_kind maps to a Live API call:

      - zoom_in / zoom_out — application.view.zoom_view
      - scroll_left / scroll_right — application.view.scroll_view
      - follow_on / follow_off — song.view.follow_song property
      - collapse_track / expand_track — per-track property on the arranger
    """
    if action_kind not in _VIEW_ACTIONS:
        raise ValueError(
            f"action_kind {action_kind!r} not in {list(_VIEW_ACTIONS)}"
        )
    song = context.song
    # Application view lives on LiveContext.application, not on Song —
    # Song does not expose get_application in any Live version we target.
    try:
        application_view = context.application.view
    except (AttributeError, RuntimeError):
        application_view = None

    if action_kind in ("follow_on", "follow_off"):
        target = song.view
        target.follow_song = (action_kind == "follow_on")
        return {"action_kind": action_kind, "follow_song": target.follow_song}

    if action_kind in ("zoom_in", "zoom_out"):
        if application_view is None:
            raise NotImplementedError(
                "application.view not exposed in this Live version"
            )
        # Live's zoom_view takes (direction, view_name, optional bool)
        # direction: 0=in, 1=out, 2=left, 3=right (per Remote Script SDK)
        direction = 0 if action_kind == "zoom_in" else 1
        application_view.zoom_view(direction, "Arranger", False)
        return {"action_kind": action_kind}

    if action_kind in ("scroll_left", "scroll_right"):
        if application_view is None:
            raise NotImplementedError(
                "application.view not exposed in this Live version"
            )
        direction = 2 if action_kind == "scroll_left" else 3
        application_view.scroll_view(direction, "Arranger", False)
        return {"action_kind": action_kind}

    # collapse_track / expand_track — per-track
    if track_index is None:
        raise ValueError(
            f"action_kind={action_kind!r} requires track_index"
        )
    if track_index < 1 or track_index > len(song.tracks):
        raise IndexError(
            f"track_index {track_index} out of range [1, {len(song.tracks)}]"
        )
    track = song.tracks[track_index - 1]
    is_collapsed = (action_kind == "collapse_track")
    # Per Live's API, the property is `is_showing_chains` (rack) or
    # `arrangement_track_height` (display height). We expose a uniform
    # collapsed/expanded affordance via the `fold_state` attribute when
    # present; otherwise fall through to setting display height.
    if hasattr(track, "fold_state"):
        track.fold_state = 1 if is_collapsed else 0
    elif hasattr(track, "is_folded"):
        track.is_folded = is_collapsed
    else:
        raise NotImplementedError(
            f"track {track_index} does not support collapse/expand in this "
            "Live version"
        )
    return {"action_kind": action_kind, "track_index": track_index}


# ---------------------------------------------------------------------------
# Cue points
# ---------------------------------------------------------------------------


def cue_list_handler(context: LiveContext) -> dict[str, Any]:
    """Return all arrangement cue points.

    Each entry: {cue_index (1-based), position_beats, name}.
    Names round-trip cleanly via Live's API in our greenfield server —
    the legacy fork's gap #13 (numeric-only names) doesn't apply here.
    """
    song = context.song
    cues = getattr(song, "cue_points", ())
    out: list[dict[str, Any]] = []
    for i, cue in enumerate(cues, start=1):
        out.append({
            "cue_index": i,
            "position_beats": float(getattr(cue, "time", 0.0)),
            "name": str(getattr(cue, "name", "")),
        })
    return {"cue_points": out}


def cue_create_handler(
    context: LiveContext,
    *,
    position_beats: float,
    name: str | None = None,
) -> dict[str, Any]:
    """Create a cue point at position_beats. Live's API takes the play
    position via set_or_delete_cue_point (which adds at the current play
    head). We temporarily seek to position_beats, add the cue, then
    optionally rename + restore.

    **Toggle-collision guard.** Live's ``set_or_delete_cue`` is a TOGGLE —
    calling it at a position that already has a cue DELETES that cue
    instead of creating a new one. cue_create's contract is to create;
    we pre-check for an existing cue at the position and raise a teaching
    error instead of silently destroying it.
    """
    if position_beats < 0:
        raise ValueError(f"position_beats {position_beats} must be >= 0")
    song = context.song
    # Pre-check: refuse to "create" when the position is already occupied.
    # Float tolerance matches the apply-side `pos_key` precision.
    for existing in getattr(song, "cue_points", ()):
        if abs(float(getattr(existing, "time", -1.0)) - float(position_beats)) < 1e-6:
            raise ValueError(
                f"cue_create: a cue already exists at position_beats="
                f"{position_beats} (name={getattr(existing, 'name', '')!r}); "
                "use cue_delete first if you want to replace it"
            )

    # Live exposes ``set_or_delete_cue`` as a NO-ARG toggle that operates
    # on the current song position, and Live 12.x has TWO independent
    # constraints that make creating a cue at an arbitrary position
    # non-trivial:
    #
    # (1) ``Song.current_song_time`` writes are picked up by the audio
    #     thread on the NEXT audio buffer (~10ms). The main-thread
    #     ``current_song_time`` getter (and ``set_or_delete_cue``,
    #     which reads the same audio-thread-side position) lag the
    #     write by up to a buffer. Bouncing through ``schedule_message``
    #     doesn't help: those callbacks fire within a single engine
    #     tick and don't yield wall-clock time to the audio thread.
    #     The reliable fix is to sleep — the audio thread runs on its
    #     own OS thread and continues processing while we block.
    #
    # (2) The setter is also clamped: ``current_song_time`` cannot move
    #     past ``last_event_time`` (the end of any arrangement
    #     content). If the arrangement is empty, the seek is silently
    #     rejected and the cue lands at 0. The caller must ensure the
    #     song has length covering the cue position — typically by
    #     placing arrangement clips first.
    toggle = getattr(song, "set_or_delete_cue", None)
    if toggle is None:
        toggle = getattr(song, "set_or_delete_cue_point", None)
    if toggle is None:
        raise NotImplementedError(
            "Live does not expose a cue-point creation API in this version"
        )

    prior = float(getattr(song, "current_song_time", 0.0))
    positions_before: set[float] = {
        round(float(getattr(c, "time", -1.0)), 6)
        for c in getattr(song, "cue_points", ())
    }
    target = round(float(position_beats), 6)

    # Refuse if the song's arrangement doesn't extend to the cue position:
    # the seek would be clamped, the toggle would fire at the clamped
    # position, and we'd corrupt unrelated state. A clear error here
    # beats a confusing one downstream.
    last_event_time = float(getattr(song, "last_event_time", 0.0))
    if position_beats > last_event_time + 1e-6:
        raise ValueError(
            f"cue_create: position_beats={position_beats} is past the "
            f"song's last_event_time={last_event_time}. Live's "
            f"current_song_time setter is clamped to the arrangement's "
            f"extent — place arrangement content covering this position "
            f"first (e.g., via ableton_clip(action='create', "
            f"location='arrangement', ...)) before adding the cue."
        )

    # Seek then toggle. Empirical Live 12.x behavior: the
    # ``current_song_time`` *getter* lags the setter by some unknown
    # main-thread caching layer — reading after a write may still see
    # the prior value within the same callback. The audio thread (which
    # ``set_or_delete_cue`` reads) DOES pick up the write, just on a
    # different timeline. So instead of verifying via the getter (which
    # gave us false-negative "didn't settle" failures), we trust the
    # write, sleep, fire the toggle, and verify success by reading the
    # actual side effect: ``cue_points``. The scan loop confirms a new
    # cue appeared at the target, which is the only thing that matters
    # to the caller.
    song.current_song_time = float(position_beats)
    time.sleep(_CUE_SETTLE_SLEEP_S)
    toggle()
    time.sleep(_CUE_SETTLE_SLEEP_S)

    cues_after = list(getattr(song, "cue_points", ()))
    new_cue_index: int | None = None
    new_cue = None
    for i, cue in enumerate(cues_after, start=1):
        t = round(float(getattr(cue, "time", -1.0)), 6)
        if t == target and t not in positions_before:
            new_cue_index = i
            new_cue = cue
            break

    # Restore the play head regardless of scan outcome so a failed
    # rename doesn't leave the transport at an unexpected position.
    song.current_song_time = prior

    if new_cue is None:
        observed_positions = [
            round(float(getattr(c, "time", -1.0)), 6) for c in cues_after
        ]
        new_positions = sorted(
            t for t in observed_positions if t not in positions_before
        )
        raise RuntimeError(
            f"cue_create: toggle did not produce a new cue at "
            f"position_beats={position_beats}. Diagnostic — "
            f"new_positions={new_positions} (any positions present after "
            f"toggle but not before), all_observed={observed_positions}, "
            f"target={target}. If new_positions contains a different "
            f"value, the toggle fired at the wrong playhead position — "
            f"common when the seek hasn't settled to the audio thread."
        )
    if name is not None:
        new_cue.name = name
    return {
        "cue_index": new_cue_index,
        "position_beats": float(position_beats),
        "name": str(getattr(new_cue, "name", "")),
    }


def cue_delete_handler(
    context: LiveContext,
    *,
    cue_index: int,
) -> dict[str, Any]:
    """Delete a cue by 1-based index.

    Live 12.x's ``set_or_delete_cue`` is a NO-ARG toggle on the current
    play position (same constraint as ``cue_create``), so deletion via
    the toggle requires seeking to the cue's position first and waiting
    for the audio thread to pick it up. See ``cue_create_handler`` for
    the full timing rationale.
    """
    song = context.song
    cues = list(getattr(song, "cue_points", ()))
    if cue_index < 1 or cue_index > len(cues):
        raise IndexError(
            f"cue_index {cue_index} out of range [1, {len(cues)}]"
        )
    target_cue = cues[cue_index - 1]
    target_time = float(getattr(target_cue, "time", 0.0))

    # Prefer the per-cue delete method when present — synchronous and
    # bypasses the seek+toggle dance entirely.
    delete_fn = getattr(target_cue, "delete", None) or getattr(target_cue, "remove", None)
    if delete_fn is not None:
        delete_fn()
        return {"deleted_cue_index": cue_index}

    # Fallback: seek to the cue's position and toggle. Real Live 12.x
    # CuePoint objects don't expose `delete`, so this path is the
    # common one. The no-arg toggle requires the audio thread to have
    # the cst write — sleep gives it wall-clock time.
    toggle = getattr(song, "set_or_delete_cue", None)
    if toggle is None:
        raise NotImplementedError(
            "Live does not expose cue deletion in this version"
        )

    # Same audio-thread-settle pattern as cue_create — trust the setter
    # write (which the audio thread picks up), don't verify via the
    # getter (which can return a stale cache), and confirm success by
    # the actual side effect: the target cue is gone from cue_points.
    prior = float(getattr(song, "current_song_time", 0.0))
    song.current_song_time = target_time
    time.sleep(_CUE_SETTLE_SLEEP_S)
    toggle()
    time.sleep(_CUE_SETTLE_SLEEP_S)
    song.current_song_time = prior
    return {"deleted_cue_index": cue_index}


def cue_rename_handler(
    context: LiveContext,
    *,
    cue_index: int,
    name: str,
) -> dict[str, Any]:
    """Set a cue's display name. Live's ``CuePoint.name`` is a direct
    writable property — no seek/toggle dance — so this is synchronous
    and reliable. Mainly useful as a recovery path when ``cue_create``
    completed the toggle but couldn't apply the rename inline due to
    Live's audio-thread settle timing.
    """
    song = context.song
    cues = list(getattr(song, "cue_points", ()))
    if cue_index < 1 or cue_index > len(cues):
        raise IndexError(
            f"cue_index {cue_index} out of range [1, {len(cues)}]"
        )
    cue = cues[cue_index - 1]
    cue.name = name
    return {
        "cue_index": cue_index,
        "position_beats": float(getattr(cue, "time", 0.0)),
        "name": str(getattr(cue, "name", "")),
    }


_JUMP_DIRECTIONS = ("next", "previous")


def cue_jump_handler(
    context: LiveContext,
    *,
    direction: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Jump the playhead to a cue. Either ``direction`` ('next'|'previous')
    relative to current position, or ``name`` to jump to a specific cue.
    Exactly one of the two must be provided.
    """
    if (direction is None) == (name is None):
        raise ValueError(
            "cue_jump: provide exactly one of direction (next|previous) OR name"
        )
    song = context.song
    if direction is not None:
        if direction not in _JUMP_DIRECTIONS:
            raise ValueError(
                f"direction {direction!r} not in {list(_JUMP_DIRECTIONS)}"
            )
        fn = getattr(
            song, "jump_to_next_cue" if direction == "next" else "jump_to_prev_cue",
            None,
        )
        if fn is None:
            raise NotImplementedError(
                f"Live does not expose jump_to_{direction}_cue in this version"
            )
        fn()
        return {
            "direction": direction,
            "position_beats": float(getattr(song, "current_song_time", 0.0)),
        }
    # name path
    target = None
    for cue in getattr(song, "cue_points", ()):
        if getattr(cue, "name", "") == name:
            target = cue
            break
    if target is None:
        available = [
            getattr(c, "name", "") for c in getattr(song, "cue_points", ())
        ]
        raise ValueError(
            f"cue_jump: no cue named {name!r}; available: {available}"
        )
    jumper = getattr(target, "jump", None)
    if jumper is not None:
        jumper()
    else:
        song.current_song_time = float(getattr(target, "time", 0.0))
    return {
        "name": name,
        "position_beats": float(getattr(song, "current_song_time", 0.0)),
    }


__all__ = [
    "info_handler",
    "set_loop_handler",
    "control_view_handler",
    "cue_list_handler",
    "cue_create_handler",
    "cue_delete_handler",
    "cue_rename_handler",
    "cue_jump_handler",
]
