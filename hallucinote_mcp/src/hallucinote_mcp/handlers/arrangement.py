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

import logging
import time
from typing import Any

from ..dispatcher import LiveContext


logger = logging.getLogger(__name__)


# How long the cue handlers wait in wall-clock time for
# ``Song.current_song_time`` to settle to a write before reading or
# toggling at the new position.
#
# W3-F (2026-05-18) — ROOT-CAUSE REWRITE of the settle pattern.
#
# Wave-2 W2-F introduced a poll-until-confirmed loop that ran ENTIRELY
# on Live's main thread (dispatcher wraps every handler in
# ``run_on_main``). The poll body called ``time.sleep`` between reads.
# Empirically observed 2026-05-18: every first-call ``cue_create``
# timed out at 3.0s with ``last_observed = <previous target>``, then a
# retry succeeded immediately. The seek itself completed — the next
# request always saw the updated mirror — but our poll loop never did.
#
# Why: ``Song.current_song_time`` setters queue an update for the audio
# thread (~10ms propagation). The main thread's Python-visible getter
# reads a mirror that's refreshed via main-thread event-pump callbacks
# from the audio thread. When the handler runs on the main thread and
# ``time.sleep`` s in a loop, the main thread is BLOCKED — the very
# thread that has to pump those callbacks. The audio thread updates its
# internal value, but the mirror never refreshes because the main
# thread is asleep. Once the handler returns (or times out), the main
# thread resumes its event loop, processes the queued mirror update,
# and the NEXT request sees the new value.
#
# The architectural fix: this helper now runs on the WORKER (TCP-
# listener) thread. Each "read the position" iteration bounces through
# ``context.run_on_main`` (a brief main-thread bout that pumps cleanly).
# Between iterations, ``time.sleep`` on the WORKER thread — the main
# thread is free to process audio-thread callbacks and refresh the
# mirror. The same architectural change applies to the toggle/verify
# steps in cue_create / cue_delete / cue_create_batch: each Live touch
# is its own main-thread bout; wall-clock waits happen between bouts on
# the worker thread.
#
# Action contract: ``cue_create`` / ``cue_create_batch`` / ``cue_delete``
# are registered with ``runs_on_worker=True`` (schema.Action). The
# dispatcher invokes them directly on the worker thread; the handlers
# call ``context.run_on_main(fn)`` for each Live touch themselves.
_CUE_SETTLE_TIMEOUT_S = 3.0
_CUE_SETTLE_POLL_S = 0.05
_CUE_SETTLE_TOLERANCE_BEATS = 0.001  # ~1ms in beats; matches Live's quantization


def _wait_for_song_time_on_worker(
    context: LiveContext,
    target_beats: float,
    *,
    max_wait_s: float = _CUE_SETTLE_TIMEOUT_S,
    poll_interval_s: float = _CUE_SETTLE_POLL_S,
    on_timeout: "Any | None" = None,
) -> None:
    """Block on the worker thread until ``context.song.current_song_time``
    settles to ``target_beats`` (within :data:`_CUE_SETTLE_TOLERANCE_BEATS`).

    Caller invariant: runs on the WORKER (TCP-listener) thread. Each
    poll is its own main-thread bout via ``context.run_on_main``.
    Between polls, ``time.sleep`` on the worker thread frees Live's
    main thread to pump the audio-thread → mirror propagation event
    that actually advances the mirror.

    ``on_timeout`` is an optional zero-arg callable that runs as a
    final main-thread bout immediately before ``TimeoutError`` is
    raised — useful for cleanup like restoring the prior playhead
    position. Its own exceptions are logged-and-swallowed (the primary
    TimeoutError must propagate as the actionable signal).

    The seek write itself is NOT done here — call sites typically
    fold the write into a validation+capture bout so a race-window
    between validation and seek isn't possible. Use
    :func:`_seek_and_wait_on_worker` when you want both in one call.
    """
    target = round(float(target_beats), 6)
    deadline = time.monotonic() + max_wait_s
    while True:
        def _read_position_on_main() -> float:
            return round(
                float(getattr(context.song, "current_song_time", -1.0)), 6,
            )

        actual = context.run_on_main(_read_position_on_main)
        if abs(actual - target) < _CUE_SETTLE_TOLERANCE_BEATS:
            return
        if time.monotonic() >= deadline:
            if on_timeout is not None:
                try:
                    context.run_on_main(on_timeout)
                except Exception as cleanup_exc:  # prawduct:ok-broad-except — cleanup; primary timeout must propagate
                    logger.warning(
                        "on_timeout cleanup failed (%s: %s); transport may "
                        "be parked at the in-flight target. Primary timeout "
                        "follows.",
                        type(cleanup_exc).__name__, cleanup_exc,
                    )
            raise TimeoutError(
                f"playhead seek to beat {target} did not settle within "
                f"{max_wait_s}s (last observed current_song_time={actual}). "
                "Live's audio thread may be unresponsive — stop transport "
                "and retry, or check if Live is busy with another operation."
            )
        time.sleep(poll_interval_s)


def _seek_and_wait_on_worker(
    context: LiveContext,
    target_beats: float,
    *,
    max_wait_s: float = _CUE_SETTLE_TIMEOUT_S,
    poll_interval_s: float = _CUE_SETTLE_POLL_S,
) -> None:
    """Write ``current_song_time = target_beats`` and BLOCK on the
    worker thread until Live's main-thread mirror reflects the write.

    Thin orchestration over :func:`_wait_for_song_time_on_worker` —
    sequences a main-thread seek bout, then delegates the wait.
    Useful when the call site has no pre-seek validation or capture
    state to manage; cue handlers combine the seek into their
    validation bout instead and call the wait helper directly.
    """
    def _seek_on_main() -> None:
        context.song.current_song_time = float(target_beats)

    context.run_on_main(_seek_on_main)
    _wait_for_song_time_on_worker(
        context, target_beats,
        max_wait_s=max_wait_s, poll_interval_s=poll_interval_s,
    )


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
    context: LiveContext, *, position_beats: float, name: str | None
) -> dict[str, Any]:
    """Inner cue-creation routine — runs on the WORKER thread.

    **Caller invariants:**
      - Holds ``context.live_state_lock`` (so concurrent callers can't
        observe each other's playhead writes mid-window).
      - Is running on the worker (TCP-listener) thread, not Live's main
        thread. This routine marshals every Live touch via
        ``context.run_on_main(fn)`` and ``time.sleep`` s between bouts
        to let the main thread pump audio-thread propagation events.

    Factored so ``cue_create_batch_handler`` can acquire the lock once
    and call this in a loop, paying acquire/release overhead exactly
    once while still keeping every per-cue window serialized against
    parallel single-cue callers.

    The handler is split into four phases, each phase a separate
    main-thread bout (plus the worker-thread settle wait between
    bouts 1 and 2):

      1. Validate + capture prior state + write current_song_time.
      2. Worker-thread poll (via ``_seek_and_wait_on_worker``) until
         Live's main-thread mirror confirms the seek.
      3. Toggle ``set_or_delete_cue`` at the now-settled playhead.
      4. Verify the new cue is in ``song.cue_points``, restore the
         prior playhead position, and optionally rename.
    """
    # ---- Bout 1: validate, capture, seek (main thread) ----
    def _validate_capture_seek() -> tuple[float, frozenset[float]]:
        song = context.song
        if position_beats < 0:
            raise ValueError(f"position_beats {position_beats} must be >= 0")
        # Refuse if a cue already exists at this position.
        for existing in getattr(song, "cue_points", ()):
            if abs(float(getattr(existing, "time", -1.0)) - float(position_beats)) < 1e-6:
                raise ValueError(
                    f"cue_create: a cue already exists at position_beats="
                    f"{position_beats} (name={getattr(existing, 'name', '')!r}); "
                    "use cue_delete first if you want to replace it"
                )
        # Probe that Live exposes a cue-toggle API in this version.
        toggle = getattr(song, "set_or_delete_cue", None) or getattr(
            song, "set_or_delete_cue_point", None,
        )
        if toggle is None:
            raise NotImplementedError(
                "Live does not expose a cue-point creation API in this version"
            )
        # Refuse if the arrangement doesn't extend to the cue position:
        # the setter is clamped to ``last_event_time`` (the end of any
        # arrangement content). A seek past the extent silently fails;
        # we'd toggle at the wrong position and corrupt unrelated state.
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
        prior = float(getattr(song, "current_song_time", 0.0))
        positions_before = frozenset(
            round(float(getattr(c, "time", -1.0)), 6)
            for c in getattr(song, "cue_points", ())
        )
        # Write current_song_time HERE so bout 2's settle wait observes
        # the propagation. Combining the validate + seek in one bout
        # avoids a race where another handler creates a cue between
        # validation and seek.
        song.current_song_time = float(position_beats)
        return prior, positions_before

    prior, positions_before = context.run_on_main(_validate_capture_seek)

    # ---- Bout 2: worker-thread settle wait ----
    #
    # The seek (issued in bout 1) is queued for the audio thread. The
    # wait helper polls the main-thread mirror via run_on_main; between
    # polls the main thread is free to pump the audio-thread → mirror
    # propagation event. THIS is the W3-F fix vs. W2-F's main-thread
    # tight-poll which deadlocked the propagation it was waiting for.
    target = round(float(position_beats), 6)

    def _restore_on_timeout() -> None:
        # Cleanup bout: restore the prior playhead so a timeout doesn't
        # leave Live parked at the in-flight target.
        context.song.current_song_time = prior

    _wait_for_song_time_on_worker(
        context, target, on_timeout=_restore_on_timeout,
    )

    # ---- Bout 3: toggle (main thread) ----
    def _toggle_at_settled_playhead() -> None:
        song = context.song
        toggle = getattr(song, "set_or_delete_cue", None) or getattr(
            song, "set_or_delete_cue_point", None,
        )
        # Re-check existence (defensive — bout-1 probe could theoretically
        # be invalidated by hot-swapped Live API; cheap insurance).
        if toggle is None:
            raise NotImplementedError(
                "Live does not expose a cue-point creation API in this version"
            )
        toggle()
    context.run_on_main(_toggle_at_settled_playhead)

    # ---- Worker-thread slack for the toggle to be visible ----
    time.sleep(_CUE_SETTLE_POLL_S)

    # ---- Bout 4: scan + restore + rename (main thread) ----
    def _scan_restore_rename() -> dict[str, Any]:
        song = context.song
        cues_after = list(getattr(song, "cue_points", ()))
        new_cue_index: int | None = None
        new_cue = None
        for i, cue in enumerate(cues_after, start=1):
            t = round(float(getattr(cue, "time", -1.0)), 6)
            if t == target and t not in positions_before:
                new_cue_index = i
                new_cue = cue
                break

        # Restore playhead regardless of scan outcome.
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

    return context.run_on_main(_scan_restore_rename)


def cue_create_handler(
    context: LiveContext,
    *,
    position_beats: float,
    name: str | None = None,
) -> dict[str, Any]:
    """Create a cue point at position_beats.

    **Threading (W3-F):** Registered with ``runs_on_worker=True`` —
    this handler runs on the TCP-listener (worker) thread, not Live's
    main thread. It marshals each Live touch through
    ``context.run_on_main(fn)`` and ``time.sleep`` s between the seek-
    write and the toggle so Live's main thread can pump the audio-thread
    propagation event that updates the ``current_song_time`` mirror. The
    pre-W3-F implementation ran entirely on the main thread and
    deadlocked: the very thread that needed to pump the mirror update
    was the one sleeping in the poll loop.

    **Toggle-collision guard.** Live's ``set_or_delete_cue`` is a TOGGLE —
    calling it at a position that already has a cue DELETES that cue
    instead of creating a new one. cue_create's contract is to create;
    we pre-check for an existing cue at the position and raise a teaching
    error instead of silently destroying it.

    **Parallel-call safety (B-21).** The seek + audio-thread-settle +
    toggle + verify window is held under ``context.live_state_lock``
    (acquired on the worker thread) so concurrent callers can't observe
    each other's playhead writes mid-window. For multi-cue pushes,
    prefer ``cue_create_batch`` — it pays the lock overhead once.
    """
    with context.live_state_lock:
        return _create_one_cue_locked(
            context, position_beats=position_beats, name=name
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

    # W3-F: each per-cue iteration runs through _create_one_cue_locked
    # which is a worker-thread routine. The lock is acquired once on the
    # worker thread for the whole batch.
    results: list[dict[str, Any]] = []
    with context.live_state_lock:
        for position_beats, name in parsed:
            results.append(
                _create_one_cue_locked(
                    context, position_beats=position_beats, name=name
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
    for the audio thread to pick it up.

    **Threading (W3-F):** Registered with ``runs_on_worker=True``. The
    seek+settle+toggle+verify sequence is broken into main-thread bouts
    interleaved with worker-thread waits, for the same deadlock-
    avoidance reason as ``cue_create_handler`` (see its docstring).

    Fast path: if the ``CuePoint`` exposes ``.delete()`` or ``.remove()``
    directly, we skip the seek+toggle dance entirely — that method is
    synchronous and bypasses the audio-thread race. Empirically Live
    12.4's CuePoint objects DON'T expose this, so the slow path is the
    common one.
    """
    # ---- Bout 1: resolve target + fast-path attempt (main thread) ----
    def _resolve_and_try_fast_path() -> dict[str, Any] | None:
        """Return the result dict if the fast path landed; else return
        a structured continuation marker for the slow path."""
        song = context.song
        cues = list(getattr(song, "cue_points", ()))
        if cue_index < 1 or cue_index > len(cues):
            raise IndexError(
                f"cue_index {cue_index} out of range [1, {len(cues)}]"
            )
        target_cue = cues[cue_index - 1]
        target_time = float(getattr(target_cue, "time", 0.0))

        delete_fn = getattr(target_cue, "delete", None) or getattr(
            target_cue, "remove", None,
        )
        if delete_fn is not None:
            delete_fn()
            return {"deleted_cue_index": cue_index, "_done": True}

        toggle = getattr(song, "set_or_delete_cue", None)
        if toggle is None:
            raise NotImplementedError(
                "Live does not expose cue deletion in this version"
            )
        return {
            "_done": False,
            "target_time": target_time,
            "prior_song_time": float(getattr(song, "current_song_time", 0.0)),
        }

    state = context.run_on_main(_resolve_and_try_fast_path)
    if state["_done"]:
        # Fast path landed; pop the sentinel and return.
        state.pop("_done")
        return state
    target_time: float = state["target_time"]
    prior: float = state["prior_song_time"]

    # Slow path — same shape as cue_create's worker-thread split.
    # Acquire the per-Live lock for the seek+settle+toggle+verify
    # window; concurrent cst writers (cue_create, cue_jump, seek)
    # could otherwise race the audio thread (B-21).
    target_pos_key = round(target_time, 6)
    with context.live_state_lock:
        # ---- Bout 2: write current_song_time (main thread) ----
        def _seek() -> None:
            context.song.current_song_time = float(target_time)
        context.run_on_main(_seek)

        try:
            # ---- Worker-thread settle wait (shared helper) ----
            _wait_for_song_time_on_worker(context, target_pos_key)

            # ---- Bout 3: toggle (main thread) ----
            def _toggle() -> None:
                song = context.song
                toggle = getattr(song, "set_or_delete_cue", None)
                if toggle is None:
                    raise NotImplementedError(
                        "Live does not expose cue deletion in this version"
                    )
                toggle()
            context.run_on_main(_toggle)

            # Worker-thread slack for the toggle to be visible.
            time.sleep(_CUE_SETTLE_POLL_S)

            # ---- Bout 4: verify (main thread) ----
            def _verify_deleted() -> None:
                cues_after = list(getattr(context.song, "cue_points", ()))
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
            context.run_on_main(_verify_deleted)
        finally:
            # Restore the playhead — best effort; raise nothing here
            # because the function's primary exception (if any) is the
            # real signal.
            def _restore() -> None:
                context.song.current_song_time = prior
            try:
                context.run_on_main(_restore)
            except Exception as restore_exc:  # prawduct:ok-broad-except — cleanup; primary exception takes precedence
                logger.warning(
                    "cue_delete: playhead restore failed (%s: %s); "
                    "transport may be parked at the cue's position. "
                    "Primary cue_delete outcome takes precedence.",
                    type(restore_exc).__name__, restore_exc,
                )

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

    **Threading (W3-F follow-up):** Registered with ``runs_on_worker=True``
    because this handler acquires ``context.live_state_lock`` and the
    lock is an ``RLock`` shared with worker-thread holders
    (``cue_create`` etc.). Pre-fix state ran on the main thread,
    deadlocking against worker-thread cue ops. Pure-Python validation
    runs on the worker; each Live touch is marshaled through
    ``run_on_main``.
    """
    if (direction is None) == (name is None):
        raise ValueError(
            "cue_jump: provide exactly one of direction (next|previous) OR name"
        )
    if direction is not None:
        if direction not in _JUMP_DIRECTIONS:
            raise ValueError(
                f"direction {direction!r} not in {list(_JUMP_DIRECTIONS)}"
            )

        def _jump_by_direction_on_main() -> float:
            song = context.song
            fn = getattr(
                song,
                "jump_to_next_cue" if direction == "next" else "jump_to_prev_cue",
                None,
            )
            if fn is None:
                raise NotImplementedError(
                    f"Live does not expose jump_to_{direction}_cue in this version"
                )
            fn()
            return float(getattr(song, "current_song_time", 0.0))

        with context.live_state_lock:
            position_after = context.run_on_main(_jump_by_direction_on_main)
        return {
            "direction": direction,
            "position_beats": position_after,
        }

    # name path
    def _jump_by_name_on_main() -> float:
        song = context.song
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
        return float(getattr(song, "current_song_time", 0.0))

    with context.live_state_lock:
        position_after = context.run_on_main(_jump_by_name_on_main)
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
