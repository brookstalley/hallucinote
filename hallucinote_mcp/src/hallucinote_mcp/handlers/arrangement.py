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
# fixed 200ms sleep used pre-Wave-2 was unreliable under stopped-
# transport (W2-4): when the playhead is being moved a meaningful
# distance from the prior position, propagation can exceed 200ms.
# The post-toggle scan then sees set_or_delete_cue having fired at the
# OLD playhead (or no movement at all).
#
# Wave-2 W2-F replaces the fixed sleep with a poll-until-confirmed
# pattern: ``_seek_then_settle`` writes ``current_song_time`` and
# polls the getter (which lags the write by the same audio-thread
# delay set_or_delete_cue reads from) until the value matches the
# target. The poll has a generous timeout (defaults to 3s) — far
# beyond the empirical worst case but bounded so a permanently-stuck
# audio thread surfaces a clear timeout rather than hanging.
_CUE_SETTLE_TIMEOUT_S = 3.0
_CUE_SETTLE_POLL_S = 0.05
_CUE_SETTLE_TOLERANCE_BEATS = 0.001  # ~1ms in beats; matches Live's quantization


def _seek_then_settle(
    song: Any,
    target_beats: float,
    *,
    max_wait_s: float = _CUE_SETTLE_TIMEOUT_S,
    poll_interval_s: float = _CUE_SETTLE_POLL_S,
) -> None:
    """Seek the arrangement playhead and BLOCK until the audio thread
    confirms the move.

    Live 12.4 makes ``Song.current_song_time`` writes asynchronously
    visible — both the getter and ``set_or_delete_cue``'s read of the
    audio-thread playhead lag the write by an audio buffer (often more
    when transport is stopped). The pre-Wave-2 implementation used a
    fixed 200ms sleep, which empirically wasn't enough (W2-4 — playhead
    far from target meant the toggle fired at the prior position). This
    helper polls the getter until it confirms the target, then returns.

    Raises ``TimeoutError`` if the playhead hasn't moved within
    ``max_wait_s``. Tests with a synchronous fake see the move
    instantly and return on the first poll.
    """
    target = round(float(target_beats), 6)
    song.current_song_time = float(target_beats)

    deadline = time.monotonic() + max_wait_s
    while True:
        actual = round(float(getattr(song, "current_song_time", -1.0)), 6)
        if abs(actual - target) < _CUE_SETTLE_TOLERANCE_BEATS:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"playhead seek to beat {target} did not settle within "
                f"{max_wait_s}s (last observed current_song_time={actual}). "
                "Live's audio thread may be unresponsive — stop transport "
                "and retry, or check if Live is busy with another operation."
            )
        time.sleep(poll_interval_s)


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
    # Live 12.4: only foldable tracks (Group tracks, Drum/Instrument racks
    # exposed at track level) accept collapse/expand. Writing fold_state to
    # a regular MIDI / audio track raises a raw ``RuntimeError: This Track
    # can not be collapsed``. Pre-check ``is_foldable`` so we surface a
    # teaching error before reaching Live's raw exception (Wave-1 B-13).
    if not bool(getattr(track, "is_foldable", False)):
        track_name = getattr(track, "name", f"track {track_index}")
        hint = (
            "Create a group containing the tracks you want to collapse "
            "before calling this action."
            if action_kind == "collapse_track"
            else "Only group tracks have a foldable state to expand."
        )
        raise ValueError(
            f"{action_kind!r}: track {track_index} ({track_name!r}) is not "
            "a foldable track; only group tracks (and rack-typed tracks) "
            f"can be collapsed or expanded. {hint}"
        )
    is_collapsed = (action_kind == "collapse_track")
    if hasattr(track, "fold_state"):
        track.fold_state = 1 if is_collapsed else 0
    elif hasattr(track, "is_folded"):
        track.is_folded = is_collapsed
    else:
        raise NotImplementedError(
            f"track {track_index} reports is_foldable but exposes neither "
            "fold_state nor is_folded; Live API surface unexpected"
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


def _create_one_cue_locked(
    song: Any, *, position_beats: float, name: str | None
) -> dict[str, Any]:
    """Inner cue-creation routine. **Caller must hold the live_state_lock.**

    Factored out so ``cue_create_batch_handler`` can acquire the lock
    once and call this in a loop, paying only one set of acquire/release
    overhead while still keeping every per-cue seek+settle+toggle window
    serialized against parallel single-cue callers.
    """
    if position_beats < 0:
        raise ValueError(f"position_beats {position_beats} must be >= 0")
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

    # Seek-then-toggle with poll-confirmed settle. Wave-2 W2-F replaces
    # the prior fixed-200ms-sleep pattern with `_seek_then_settle`,
    # which polls the audio-thread-visible playhead until it matches
    # the target. set_or_delete_cue then fires at the confirmed
    # position. We still verify via the cue_points side effect after
    # the toggle (the toggle itself is a brief audio-thread operation
    # that the post-write read picks up reliably).
    _seek_then_settle(song, float(position_beats))
    toggle()
    time.sleep(_CUE_SETTLE_POLL_S)  # one poll-interval slack for the toggle

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

    **Parallel-call safety (B-21).** The seek + audio-thread-settle +
    toggle + settle window is held under ``context.live_state_lock`` so
    concurrent callers can't observe each other's playhead writes
    before the audio thread picks them up. Empirical Live 12.x
    behavior: even with 200ms main-thread sleeps, parallel handlers'
    cst writes race because the audio thread processes them on its own
    buffer-aligned schedule. The lock makes the per-cue window atomic.
    For multi-cue pushes, prefer ``cue_create_batch`` — it pays the
    lock overhead once.
    """
    with context.live_state_lock:
        return _create_one_cue_locked(
            context.song, position_beats=position_beats, name=name
        )


def cue_create_batch_handler(
    context: LiveContext, *, cues: list[Any],
) -> dict[str, Any]:
    """Create multiple cues in one call, holding ``live_state_lock`` once.

    Each entry in ``cues`` is ``{"position_beats": float, "name": str?}``.
    Returns ``{"cue_count": N, "cues": [...]}`` where each result is the
    same shape as ``cue_create``'s return value, in submission order.

    **Index caveat**: the reported ``cue_index`` is the position in
    ``song.cue_points`` AT THE TIME each cue was created. Because Live
    keeps the list sorted by position, inserting an earlier cue shifts
    later indices. Callers needing the final stable index mapping
    should call ``cue_list`` after the batch.
    """
    if not isinstance(cues, list):
        raise ValueError(
            f"cue_create_batch: cues must be a list, got {type(cues).__name__}"
        )
    if not cues:
        raise ValueError("cue_create_batch: cues list is empty")

    # Pre-validate the whole list so we fail loudly before any partial
    # mutation rather than half-completing the batch.
    parsed: list[tuple[float, str | None]] = []
    seen_positions: set[float] = set()
    for i, entry in enumerate(cues):
        if not isinstance(entry, dict):
            raise ValueError(
                f"cue_create_batch: cues[{i}] must be a dict, got "
                f"{type(entry).__name__}"
            )
        if "position_beats" not in entry:
            raise ValueError(
                f"cue_create_batch: cues[{i}] missing required key "
                f"'position_beats'"
            )
        pos_raw = entry["position_beats"]
        if not isinstance(pos_raw, (int, float)) or isinstance(pos_raw, bool):
            raise ValueError(
                f"cue_create_batch: cues[{i}].position_beats must be a "
                f"number, got {type(pos_raw).__name__}"
            )
        pos = float(pos_raw)
        rounded = round(pos, 6)
        if rounded in seen_positions:
            raise ValueError(
                f"cue_create_batch: cues[{i}].position_beats={pos} is a "
                f"duplicate within the batch — Live's cue list rejects "
                f"two cues at the same position"
            )
        seen_positions.add(rounded)
        name_raw = entry.get("name")
        if name_raw is not None and not isinstance(name_raw, str):
            raise ValueError(
                f"cue_create_batch: cues[{i}].name must be a string, got "
                f"{type(name_raw).__name__}"
            )
        parsed.append((pos, name_raw))

    results: list[dict[str, Any]] = []
    with context.live_state_lock:
        song = context.song
        for position_beats, name in parsed:
            results.append(
                _create_one_cue_locked(
                    song, position_beats=position_beats, name=name
                )
            )
    return {"cue_count": len(results), "cues": results}


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

    # Hold ``live_state_lock`` across the seek+toggle+verify window for
    # the same parallel-safety reason as cue_create (B-21): concurrent
    # cst writers would otherwise race the audio thread.
    #
    # Wave-2 W2-F: use _seek_then_settle (poll-confirmed) instead of a
    # fixed sleep, and verify via cue_points side effect (W2-6) — the
    # pre-Wave-2 implementation returned ok:true after the toggle even
    # when the cue was still present (the toggle fired at the wrong
    # position due to W2-4's settle race). The playhead is restored in
    # a finally clause so timeout / verify failures don't leave the
    # transport parked at the cue's position (symmetric with
    # cue_create's restore path).
    target_pos_key = round(target_time, 6)
    with context.live_state_lock:
        prior = float(getattr(song, "current_song_time", 0.0))
        try:
            _seek_then_settle(song, target_time)
            toggle()
            time.sleep(_CUE_SETTLE_POLL_S)  # one poll-interval slack for toggle
            cues_after = list(getattr(song, "cue_points", ()))
            still_present = any(
                abs(round(float(getattr(c, "time", -1.0)), 6) - target_pos_key) < 1e-6
                for c in cues_after
            )
            if still_present:
                raise RuntimeError(
                    f"cue_delete: toggle did not remove the cue at "
                    f"position_beats={target_time}. The cue is still "
                    "present in song.cue_points after the toggle. This "
                    "usually means the audio-thread playhead didn't "
                    "settle to the target position before "
                    "set_or_delete_cue fired — try retrying, or use "
                    "cue_rename to mark it for manual deletion in Live."
                )
        finally:
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
        # jump_to_{next,prev}_cue mutates current_song_time on Live's side,
        # so it falls under the same parallel-safety contract as cue_create /
        # cue_delete / seek (B-21). Holding live_state_lock here keeps the
        # contract honest.
        with context.live_state_lock:
            fn()
            position_after = float(getattr(song, "current_song_time", 0.0))
        return {
            "direction": direction,
            "position_beats": position_after,
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
    # Both paths write current_song_time (either Live's CuePoint.jump() does
    # it internally, or we set it directly). Same B-21 race surface as the
    # direction path above.
    with context.live_state_lock:
        if jumper is not None:
            jumper()
        else:
            song.current_song_time = float(getattr(target, "time", 0.0))
        position_after = float(getattr(song, "current_song_time", 0.0))
    return {
        "name": name,
        "position_beats": position_after,
    }


__all__ = [
    "info_handler",
    "set_loop_handler",
    "control_view_handler",
    "cue_list_handler",
    "cue_create_handler",
    "cue_create_batch_handler",
    "cue_delete_handler",
    "cue_rename_handler",
    "cue_jump_handler",
]
